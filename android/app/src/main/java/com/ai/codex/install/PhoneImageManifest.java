package com.ai.codex.install;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;

/** Verifies APK-authenticated immutable inputs after device provisioning.
 * Profile, DNS and keyring state deliberately have separate real validators. */
public final class PhoneImageManifest {
    private PhoneImageManifest() {}
    public interface ModeReader { int mode(Path path) throws IOException; }
    private static final Set<String> REQUIRED = Set.of(
        "usr/bin/env", "usr/bin/bash", "usr/bin/python3.13", "usr/bin/dbus-run-session",
        "usr/bin/gnome-keyring-daemon", "usr/bin/xfwm4", "usr/bin/wmctrl",
        "usr/lib/chatgpt/ChatGPT", "usr/lib/chatgpt/resources/app.asar",
        "usr/local/bin/codex-session", "usr/local/bin/codex-native",
        "usr/local/libexec/codex/codex-native", "usr/local/libexec/codex/codex-code-mode-host",
        "usr/local/lib/codex/codex_keyring.py", "usr/local/lib/codex/codex_ime.py",
        "usr/local/lib/codex/keyboard-focus.js", "usr/local/lib/codex/install-workspace-provider.py",
        "usr/local/lib/codex/install/initialize_keyring.py", "usr/local/lib/codex/install/supervise_keyring.py",
        "usr/share/X11/xkb/rules/evdev",
        "opt/codex-gpu/mesa-26.2.2-codex5/lib/libvulkan_freedreno.so");

    public static void verify(Path root, byte[] inventory, ModeReader modes) throws IOException {
        try {
            JSONObject manifest = new JSONObject(new String(inventory, java.nio.charset.StandardCharsets.UTF_8));
            if (!manifest.getString("format").equals("codex.phone-image.v1")
                    || !manifest.getString("scope").equals("immutable-launch-inputs"))
                throw new IOException("Unknown phone image inventory");
            JSONArray entries = manifest.getJSONArray("files");
            if (entries.length() < REQUIRED.size() || entries.length() > 100000)
                throw new IOException("Phone image inventory has an invalid entry count");
            Set<String> seen = new HashSet<>();
            for (int i = 0; i < entries.length(); i++) {
                if (Thread.currentThread().isInterrupted()) throw new java.io.InterruptedIOException();
                JSONObject item = entries.getJSONObject(i);
                String name = item.getString("path");
                if (!safe(name) || !seen.add(name)) throw new IOException("Unsafe or duplicate phone image path");
                Path path = root;
                String[] parts = name.split("/");
                for (int part = 0; part < parts.length - 1; part++) {
                    path = path.resolve(parts[part]);
                    if (!Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS))
                        throw new IOException("Phone image path traverses a link: " + name);
                }
                path = path.resolve(parts[parts.length - 1]);
                if ((modes.mode(path) & 07777) != item.getInt("mode"))
                    throw new IOException("Phone image permission differs: " + name);
                switch (item.getString("kind")) {
                    case "directory":
                        if (!Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Missing image directory: " + name);
                        break;
                    case "symlink":
                        if (!Files.isSymbolicLink(path) || !Files.readSymbolicLink(path).toString().equals(item.getString("target")))
                            throw new IOException("Phone image link differs: " + name);
                        break;
                    case "file":
                        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) || Files.size(path) != item.getLong("bytes")
                                || !digest(path).equals(item.getString("sha256")))
                            throw new IOException("Phone image file differs: " + name);
                        break;
                    default: throw new IOException("Unknown phone image entry type");
                }
            }
            if (!seen.containsAll(REQUIRED)) throw new IOException("Phone image omits a required launch component");
        } catch (org.json.JSONException error) { throw new IOException("Invalid phone image inventory", error); }
    }

    private static boolean safe(String value) {
        if (value.isEmpty() || value.startsWith("/") || value.indexOf('\\') >= 0) return false;
        for (char c : value.toCharArray()) if (c < 32 || c == 127) return false;
        for (String part : value.split("/", -1)) if (part.isEmpty() || part.equals(".") || part.equals("..")) return false;
        return true;
    }
    public static String digest(Path file) throws IOException {
        try (InputStream input = Files.newInputStream(file, LinkOption.NOFOLLOW_LINKS)) {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[65536];
            for (int count; (count = input.read(buffer)) != -1;) {
                if (Thread.currentThread().isInterrupted()) throw new java.io.InterruptedIOException();
                digest.update(buffer, 0, count);
            }
            StringBuilder result = new StringBuilder();
            for (byte b : digest.digest()) result.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
            return result.toString();
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
}
