package com.ai.codex.phone

import android.app.*
import android.content.*
import com.ai.codex.CodexActivity
import com.ai.codex.R
import com.ai.codex.LiveNotifications
import com.ai.codex.phone.i18n.AppStrings
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.net.Uri

object EntryRoutes {
    fun openApp(c: Context) = Intent(c, CodexActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
    fun openChat(c: Context, sessionId: String?, host: String?) = openApp(c)
    fun openUrl(c: Context, url: String) = Intent(Intent.ACTION_VIEW, Uri.parse(url))
}

/** Only this installed app can dispatch the explicit stop action. */
class PhoneStopReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val taskId = intent.getLongExtra("taskId", -1L)
        if (intent.action == "com.ai.codex.phone.STOP" && taskId > 0)
            PhoneControl.get(context).stopShownTask("用户从通知停止手机操控", taskId)
        if (intent.action == "com.ai.codex.phone.PAUSE" && taskId > 0)
            PhoneControl.get(context).pauseTask(taskId, true)
        if (intent.action == "com.ai.codex.phone.RESUME" && taskId > 0)
            PhoneControl.get(context).pauseTask(taskId, false)
    }
}
object PhoneHost {
    private const val CHANNEL = "codex-phone-task"
    private val handler by lazy { Handler(Looper.getMainLooper()) }
    private var context: Context? = null
    private var frame = 0L
    private var taskId = 0L
    private var postedAt = 0L
    private var previousLine: String? = null
    private val history = PhoneLiveHistory()
    private fun action(c: Context, task: PhoneControl.LiveTask): String = PhoneLiveText.action(
        task.line, AppStrings.get(c, R.string.phone_waived_status), AppStrings.get(c, R.string.phone_acting))
    private val publish = object : Runnable {
        override fun run() {
            val c = context ?: return
            handler.removeCallbacks(this)
            val n = c.getSystemService(NotificationManager::class.java)
            val task = PhoneControl.peek()?.liveTask()
            if (task == null) {
                n.cancel(LiveNotifications.PHONE_ID)
                taskId = 0L
                previousLine = null
                history.record(0, "")
                LiveNotifications.phoneChanged(c)
                return
            }
            val current = action(c, task)
            history.record(task.id, current)
            val line = PhoneLiveText.detail(current, task.app, task.paused, task.prompt, history.recent())
            if (task.id != taskId || previousLine != line) frame = 0L
            taskId = task.id
            previousLine = line
            n.createNotificationChannel(NotificationChannel(CHANNEL, "手机操控", NotificationManager.IMPORTANCE_LOW))
            val stop = PendingIntent.getBroadcast(c, 0, Intent(c, PhoneStopReceiver::class.java)
                .setAction("com.ai.codex.phone.STOP").setData(Uri.parse("codex-phone-stop://task/${task.id}"))
                .putExtra("taskId", task.id), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val open = PendingIntent.getActivity(c, 5170, Intent(c, PhoneSettingsActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
            val pause = PendingIntent.getBroadcast(c, 1, Intent(c, PhoneStopReceiver::class.java)
                .setAction(if (task.paused) "com.ai.codex.phone.RESUME" else "com.ai.codex.phone.PAUSE")
                .setData(Uri.parse("codex-phone-pause://task/${task.id}/${task.paused}"))
                .putExtra("taskId", task.id), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            val builder = Notification.Builder(c, CHANNEL).setSmallIcon(R.drawable.codex_notification_icon)
                .setContentTitle("Codex · 手机操控")
                .setContentText(line).setContentIntent(open).setOngoing(true)
                .setOnlyAlertOnce(true).setShowWhen(false).setTimeoutAfter(15_000L)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setPublicVersion(Notification.Builder(c, CHANNEL).setSmallIcon(R.drawable.codex_notification_icon)
                    .setContentTitle("Codex").setContentText("手机操控任务正在进行").build())
                .addAction(Notification.Action.Builder(null, if (task.paused) "继续" else "暂停", pause).build())
                .addAction(Notification.Action.Builder(null, "停止手机操控", stop).build())
            runCatching {
                n.notify(LiveNotifications.PHONE_ID, LiveNotifications.apply(c, builder, true, line, frame++).build())
                LiveNotifications.phoneChanged(c)
            }
            postedAt = SystemClock.elapsedRealtime()
            handler.postDelayed(this, LiveNotifications.SCROLL_MS)
        }
    }
    fun refreshNotification(c: Context) {
        context = c.applicationContext
        val task = PhoneControl.peek()?.liveTask()
        val observed = task?.let { action(c, it) }
        handler.post {
            // Capture intermediate steps before the notification's posting throttle.
            if (task != null && observed != null) history.record(task.id, observed)
            handler.removeCallbacks(publish)
            handler.postDelayed(publish, (postedAt + 150L - SystemClock.elapsedRealtime()).coerceAtLeast(0))
        }
    }
    fun extraTools(): List<Map<String, Any?>> = listOf(
        mapOf("name" to "status", "description" to "查看这台手机的操控开关、无障碍、Root 后台屏、当前任务及确认状态。操作手机先调用。", "inputSchema" to mapOf("type" to "object", "properties" to emptyMap<String, Any>(), "additionalProperties" to false)),
        mapOf("name" to "finish", "description" to "手机任务完成后关闭悬浮条并释放后台屏。taskId 来自 status，正在执行操作时不会结束。", "inputSchema" to mapOf("type" to "object", "properties" to mapOf("taskId" to mapOf("type" to "integer")), "required" to listOf("taskId"), "additionalProperties" to false))
    )
}
