package com.ai.codex.phone

import org.junit.Assert.*
import org.junit.Test

/** Wire-level MCP regression: actual vendored server, no Android/UI or model calls. */
class PhoneMcpIntegrationTest {
    private fun reply(server: McpServer, id: Int, method: String, params: Map<String, Any?> = emptyMap()): Map<*, *> {
        val line=server.handle(Json.write(mapOf("jsonrpc" to "2.0","id" to id,"method" to method,"params" to params)))!!
        return Json.parse(line) as Map<*, *>
    }
    @Test fun discoveryIncludesNativeToolsAndUsageInstructions() {
        val server=McpServer(PhoneToolCatalog.listJson()+PhoneHost.extraTools(), {name,_->ToolOutput(name)})
        val init=reply(server,1,"initialize",mapOf("protocolVersion" to "2025-11-25"))["result"] as Map<*, *>
        val instructions=init["instructions"] as String
        assertTrue(instructions.contains("先 status"))
        assertTrue(instructions.contains("background:true"))
        assertTrue(instructions.contains("finish(taskId)"))
        val listing=reply(server,2,"tools/list")["result"] as Map<*, *>
        val names=(listing["tools"] as List<*>).map{(it as Map<*, *>)["name"]}
        assertEquals(15,names.size)
        assertTrue(names.containsAll(listOf("status","screen","open","tap","type","collect","handoff","finish")))
        assertFalse(names.any{it.toString().startsWith("ui_") || it.toString().startsWith("vscreen_")})
    }
    @Test fun waitingToolDoesNotPreventPingDispatch() {
        val server=McpServer(PhoneToolCatalog.listJson(),{_,_->ToolOutput("waited")})
        val waiting=server.dispatch(Json.write(mapOf("id" to 1,"method" to "tools/call","params" to mapOf("name" to "handoff","arguments" to mapOf("reason" to "请用户操作")))))
        assertTrue(waiting is McpServer.Dispatch.Call)
        assertEquals(2L,(reply(server,2,"ping")["id"] as Number).toLong())
        assertTrue((waiting as McpServer.Dispatch.Call).run().contains("waited"))
    }
    @Test fun unicodeAndImagesReturnAsStructuredMcpContent() {
        val server=McpServer(PhoneToolCatalog.listJson(),{_,_->ToolOutput("输入已核对：你好",image=byteArrayOf(0,-1,10),imageMime="image/png")})
        val result=reply(server,7,"tools/call",mapOf("name" to "screen","arguments" to mapOf("image" to true)))["result"] as Map<*, *>
        val content=result["content"] as List<*>
        assertEquals("输入已核对：你好",(content[0] as Map<*, *>)["text"])
        assertEquals("AP8K",(content[1] as Map<*, *>)["data"])
        assertEquals(false,result["isError"])
    }
}
