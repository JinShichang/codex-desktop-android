package com.ai.codex.install;

import java.io.IOException;
import java.nio.file.*;
import java.util.Comparator;
import org.junit.Test;
import static org.junit.Assert.*;

public class GuestIdentityTest {
    private static final String PASSWD="root:x:0:0:root:/root:/bin/bash\ncodex:x:12345:12345::/home/codex:/bin/bash\n";
    private static final String GROUP="root:x:0:\ncodex:x:12345:\n";
    @Test public void accountComesFromProvisionedDatabase() throws Exception {
        GuestIdentity identity=GuestIdentity.parse("codex",PASSWD,GROUP);
        assertEquals("12345:12345",identity.prootIds());
        assertEquals("/home/codex",identity.home);
    }
    @Test public void legacyAccountIsExplicitAndRetainsItsIdentity() throws Exception {
        GuestIdentity identity=GuestIdentity.parse("julien",PASSWD.replace("codex","julien").replace("12345","10410"),GROUP.replace("codex","julien").replace("12345","10410"));
        assertEquals("10410:10410",identity.prootIds());
    }
    @Test public void rejectsAmbiguousPrivilegedAndInconsistentAccounts() throws Exception {
        reject(PASSWD+"other:x:12345:12345::/home/other:/bin/bash\n",GROUP);
        reject(PASSWD+"codex:x:23456:12345::/home/codex:/bin/bash\n",GROUP);
        reject(PASSWD.replace(":12345:12345:",":0:12345:"),GROUP);
        reject(PASSWD.replace("/home/codex","/home/codex/../../root"),GROUP);
        reject(PASSWD.replace("/home/codex:/bin/bash","/home/codex:/usr/sbin/nologin"),GROUP);
        reject(PASSWD,GROUP.replace("12345","23456"));
        reject(PASSWD,GROUP+"codex:x:12345:\n");
        reject(PASSWD.replace("12345","4294967295"),GROUP);
    }
    private static void reject(String passwd,String group) throws Exception {
        try { GuestIdentity.parse("codex",passwd,group); fail("Invalid account accepted"); }
        catch(IOException expected) { assertFalse(expected.getMessage().isEmpty()); }
    }
    @Test public void rejectsLinkedSelectionAndHome() throws Exception {
        Path root=Files.createTempDirectory("codex-identity-");
        try {
            Path etc=Files.createDirectory(root.resolve("etc"));
            Files.writeString(etc.resolve("passwd"),PASSWD); Files.writeString(etc.resolve("group"),GROUP);
            Files.createDirectories(root.resolve("home/codex"));
            Path selected=etc.resolve("codex-user"); Files.writeString(selected,"codex\n");
            assertEquals(12345,GuestIdentity.load(root).uid);
            Files.move(selected,etc.resolve("selected")); Files.createSymbolicLink(selected,Path.of("selected"));
            rejectLoad(root);
            Files.delete(selected); Files.writeString(selected,"codex\n");
            Files.delete(root.resolve("home/codex")); Files.createSymbolicLink(root.resolve("home/codex"),Path.of(".."));
            rejectLoad(root);
        } finally {
            try(var files=Files.walk(root)) { for(Path path:files.sorted(Comparator.reverseOrder()).toList()) Files.delete(path); }
        }
    }
    private static void rejectLoad(Path root) throws Exception {
        try { GuestIdentity.load(root); fail("Linked identity accepted"); }
        catch(IOException expected) { assertFalse(expected.getMessage().isEmpty()); }
    }
}
