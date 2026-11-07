package com.ai.codex.phone

import java.io.File
import android.util.AtomicFile
import android.system.Os

/** Codex host adapter. The upstream MCP bridge protocol is unchanged. */
object PhoneGuest {
    data class Endpoint(val abstractName: String?, val tcpPort: Int?, val token: String)
    private fun target(root: File) = File(File("/data/user/${android.os.Process.myUid() / 100000}/com.ai.codex/files/codex-tools").canonicalFile, "phone-bridge.json")
    fun writeConfig(root: File, endpoint: Endpoint) {
        val f = target(root)
        check(!java.nio.file.Files.isSymbolicLink(f.toPath()))
        check(f.parentFile!!.mkdirs() || f.parentFile!!.isDirectory)
        Os.chmod(f.parent, 448)
        val atomic = AtomicFile(f)
        val stream = atomic.startWrite()
        try {
            Os.fchmod(stream.fd, 384)
            stream.write((Json.write(mapOf("v" to 1, "abstract" to endpoint.abstractName,
                "tcpPort" to endpoint.tcpPort, "token" to endpoint.token)) + "\n").toByteArray())
            atomic.finishWrite(stream)
        } catch (e: Exception) { atomic.failWrite(stream); throw e }
    }
    fun clearConfig(root: File) { target(root).delete() }
}
