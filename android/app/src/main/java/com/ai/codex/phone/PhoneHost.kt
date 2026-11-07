package com.ai.codex.phone

import android.app.*
import android.content.*
import com.ai.codex.CodexActivity
import com.ai.codex.R

object EntryRoutes {
    fun openApp(c: Context) = Intent(c, CodexActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
    fun openChat(c: Context, sessionId: String?, host: String?) = openApp(c)
}

/** Only this installed app can dispatch the explicit stop action. */
class PhoneStopReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == "com.ai.codex.phone.STOP") PhoneControl.get(context).stopTask("用户从通知停止手机操控")
    }
}
object PhoneHost {
    private const val CHANNEL = "codex-phone-task"
    fun refreshNotification(c: Context) {
        val n = c.getSystemService(NotificationManager::class.java)
        val task = PhoneControl.peek()?.liveTask()
        if (task == null) { n.cancel(5170); return }
        n.createNotificationChannel(NotificationChannel(CHANNEL, "手机操控", NotificationManager.IMPORTANCE_LOW))
        val stop = PendingIntent.getBroadcast(c, 0, Intent(c, PhoneStopReceiver::class.java)
            .setAction("com.ai.codex.phone.STOP"), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val open = PendingIntent.getActivity(c, 5170, Intent(c, PhoneSettingsActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        runCatching { n.notify(5170, Notification.Builder(c, CHANNEL).setSmallIcon(R.drawable.codex_icon)
            .setContentTitle(if (task.paused) "手机操控已暂停" else "正在操作手机")
            .setContentText(task.line ?: task.app ?: "Codex 手机任务").setContentIntent(open).setOngoing(true)
            .addAction(Notification.Action.Builder(null, "停止手机操控", stop).build()).build()) }
    }
    fun extraTools(): List<Map<String, Any?>> = listOf(
        mapOf("name" to "status", "description" to "查看这台手机的操控开关、无障碍、Root 后台屏、当前任务及确认状态。操作手机先调用。", "inputSchema" to mapOf("type" to "object", "properties" to emptyMap<String, Any>(), "additionalProperties" to false)),
        mapOf("name" to "finish", "description" to "手机任务完成后关闭悬浮条并释放后台屏。taskId 来自 status，正在执行操作时不会结束。", "inputSchema" to mapOf("type" to "object", "properties" to mapOf("taskId" to mapOf("type" to "integer")), "required" to listOf("taskId"), "additionalProperties" to false))
    )
}
