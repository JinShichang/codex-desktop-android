package com.ai.codex.install;

import org.json.*;
import org.junit.*;
import org.junit.rules.TemporaryFolder;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.List;

public class PhoneImageManifestTest {
    @Rule public TemporaryFolder temporary = new TemporaryFolder();
    private Path root;
    private JSONObject inventory;
    // A small complete release fixture, including real ELF/script locations.
    private static final List<String> INPUTS = List.of(
        "usr/bin/env", "usr/bin/bash", "usr/bin/python3.13", "usr/bin/dbus-run-session",
        "usr/bin/gnome-keyring-daemon", "usr/bin/xfwm4", "usr/bin/wmctrl",
        "usr/lib/chatgpt/ChatGPT", "usr/lib/chatgpt/resources/app.asar",
        "usr/local/bin/codex-session", "usr/local/bin/codex-native",
        "usr/local/libexec/codex/codex-native", "usr/local/libexec/codex/codex-code-mode-host",
        "usr/local/lib/codex/codex_keyring.py", "usr/local/lib/codex/codex_ime.py",
        "usr/local/lib/codex/keyboard-focus.js", "usr/local/lib/codex/install-workspace-provider.py",
        "usr/local/lib/codex/install/initialize_keyring.py", "usr/local/lib/codex/install/supervise_keyring.py",
        "usr/share/X11/xkb/rules/evdev", "opt/codex-gpu/mesa-26.2.2-codex5/lib/libvulkan_freedreno.so");

    @Before public void fixture() throws Exception {
        Assume.assumeTrue(FileSystems.getDefault().supportedFileAttributeViews().contains("posix"));
        root = temporary.newFolder("root").toPath();
        JSONArray records = new JSONArray();
        for (String name : INPUTS) {
            Path file = root.resolve(name);
            Files.createDirectories(file.getParent());
            Files.writeString(file, "fixture:" + name);
            Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("rw-r--r--"));
            records.put(new JSONObject().put("path", name).put("kind", "file").put("mode", 0644)
                .put("bytes", Files.size(file)).put("sha256", PhoneImageManifest.digest(file)));
        }
        inventory = new JSONObject().put("format", "codex.phone-image.v1")
            .put("scope", "immutable-launch-inputs").put("files", records);
    }
    private void verify() throws IOException {
        PhoneImageManifest.verify(root, inventory.toString().getBytes(StandardCharsets.UTF_8),
            path -> ((Number) Files.getAttribute(path, "unix:mode", LinkOption.NOFOLLOW_LINKS)).intValue());
    }
    private void rejected() throws IOException {
        Assert.assertThrows(IOException.class, this::verify);
    }
    @Test public void completeInputsAdmitted() throws Exception { verify(); }
    @Test public void changedClientRejected() throws Exception {
        Files.writeString(root.resolve("usr/lib/chatgpt/resources/app.asar"), "changed archive"); rejected();
    }
    @Test public void changedExecutableModeRejected() throws Exception {
        Files.setPosixFilePermissions(root.resolve("usr/local/libexec/codex/codex-native"),
            PosixFilePermissions.fromString("rwxr-xr-x")); rejected();
    }
    @Test public void missingEngineRejected() throws Exception {
        Files.delete(root.resolve("usr/local/libexec/codex/codex-native")); rejected();
    }
    @Test public void linkParentRejectedEvenWithIdenticalFiles() throws Exception {
        Path external = temporary.getRoot().toPath().resolve("external-local");
        Files.move(root.resolve("usr/local"), external);
        Files.createSymbolicLink(root.resolve("usr/local"), external);
        rejected();
    }
    @Test public void pathTraversalRejected() throws Exception {
        inventory.getJSONArray("files").getJSONObject(0).put("path", "../outside"); rejected();
    }
    @Test public void duplicateRecordRejected() throws Exception {
        inventory.getJSONArray("files").put(inventory.getJSONArray("files").getJSONObject(0)); rejected();
    }
    @Test public void descriptorCannotOmitEngine() throws Exception {
        JSONArray records = inventory.getJSONArray("files");
        for (int i = records.length() - 1; i >= 0; i--)
            if (records.getJSONObject(i).getString("path").endsWith("/codex-native")) records.remove(i);
        // Keep the entry count above the minimum; completeness is a named contract.
        Path extra = root.resolve("extra"); Files.writeString(extra, "x");
        records.put(new JSONObject().put("path", "extra").put("kind", "file").put("mode", 0644)
            .put("bytes", 1).put("sha256", PhoneImageManifest.digest(extra)));
        rejected();
    }
    @Test public void actualGuestSymlinkVerified() throws Exception {
        Path file = root.resolve("usr/share/X11/xkb/rules/evdev");
        Files.delete(file); Files.createSymbolicLink(file, Path.of("base"));
        for (Object value : inventory.getJSONArray("files")) {
            JSONObject record = (JSONObject) value;
            if (record.getString("path").endsWith("/evdev"))
                record.put("kind", "symlink").put("mode", 0777).put("target", "base");
        }
        verify();
        Files.delete(file); Files.createSymbolicLink(file, Path.of("different")); rejected();
    }
}
