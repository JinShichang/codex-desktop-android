package com.ai.codex.phone

import android.app.AlertDialog
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.view.WindowInsets
import android.widget.*
import androidx.appcompat.app.AppCompatActivity

/** Native settings host for the vendored phone driver, without a Flutter dependency. */
class PhoneSettingsActivity : AppCompatActivity() {
    private lateinit var control: PhoneControl
    private lateinit var body: LinearLayout
    @Volatile private var alive = true
    @Volatile private var busy = false
    override fun onCreate(state: Bundle?) { super.onCreate(state); control = PhoneControl.get(this) }
    override fun onResume() { super.onResume(); control.prompts.attachActivity(this, this); render() }
    override fun onPause() { control.prompts.attachActivity(this, null); super.onPause() }
    override fun onDestroy() { alive = false; control.background.cancelUnwantedPending(); super.onDestroy() }
    private fun render() {
        val scroll = ScrollView(this)
        scroll.setOnApplyWindowInsetsListener { v, i -> val b=i.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout());v.setPadding(b.left,b.top,b.right,b.bottom);i }
        body = LinearLayout(this).apply { orientation=LinearLayout.VERTICAL; val d=(20*resources.displayMetrics.density).toInt();setPadding(d,d,d,d) }
        scroll.addView(body);setContentView(scroll)
        text("手机操控", 26)
        text("由 dsh-Go 手机操控核心提供。模型可读取屏幕文字，按需接收截图，点击、输入及滚动。你可以通过悬浮条或通知随时停止。")
        toggle("启用手机操控", control.isEnabled()) { on ->
            if (!on) { control.setEnabled(false); render() }
            else AlertDialog.Builder(this).setTitle("开启手机操控")
                .setMessage("任务所需屏幕内容会发送给你选择的模型。开启后仍需手动打开无障碍；Root 授权由 Root 管理器决定。")
                .setNegativeButton("取消") { _,_->render() }.setPositiveButton("同意并开启") { _,_->control.setEnabled(true);render() }.setOnCancelListener {render()}.show()
        }
        text("无障碍：" + if(control.a11yEnabledInSettings()) "已开启" else "未开启")
        button("打开无障碍设置") { startActivity(control.accessibilitySettingsIntent()) }
        button("允许通知 / 管理应用权限") { startActivity(control.appDetailsIntent()) }
        button("读一下当前屏幕（不会发给模型）") { work { val out=control.testScreen(); runOnUiThread { show("读屏结果",Json.write(out)) }; null } }
        text("确认方式",21)
        val modes = arrayOf("关键步骤先询问", "本任务可免确认", "始终免确认")
        val values = arrayOf("ask","task","always")
        val radio = RadioGroup(this)
        modes.forEachIndexed { index,label ->
            val b=RadioButton(this).apply {text=label;id=index+600;minHeight=(48*resources.displayMetrics.density).toInt()}
            radio.addView(b);if(control.policies().confirmMode.wire==values[index])radio.check(b.id)
        }
        radio.setOnCheckedChangeListener { _,id ->
            val mode=values[id-600]
            if(mode=="always") AlertDialog.Builder(this).setTitle("始终免确认")
                .setMessage("后续允许的手机操作会直接执行；应用名单和未解除的敏感操作限制仍生效。")
                .setNegativeButton("取消") {_,_->render()}.setPositiveButton("开启") {_,_->control.setPolicies(mapOf("confirmMode" to mode));render()}.show()
            else control.setPolicies(mapOf("confirmMode" to mode))
        };body.addView(radio)
        button("编辑应用名单") { rules() }
        text("不打扰模式 / Root",21)
        text(Json.write(control.background.status()))
        button(if(busy) "正在准备…" else "用 Root 开启后台屏（KernelSU / APatch）") {
            if(control.isEnabled()) work { control.background.setBackgroundMode("root") { alive && control.isEnabled() } }
            else show("请先开启手机操控","然后再激活 Root 后台屏。")
        }
        button("关闭后台屏并断开通道") { work { control.background.setBackgroundMode("off") } }
        button("用 Shizuku / Sui 开启") { work {
            if(!control.background.requestShizukuPermission()) control.background.setBackgroundMode("shizuku") { alive && control.isEnabled() }
            else mapOf("提示" to "请在 Shizuku 中完成授权，然后再次点击")
        } }
        button("手动配对本机 ADB") { adb() }
        text("敏感操作（默认关闭）",21)
        val u=control.policies().unlocks
        listOf(Triple("systemPages","系统设置与权限页面",u.systemPages),Triple("secretFields","密码和验证码",u.secretFields),Triple("ownApp","Codex 自身界面",u.ownApp)).forEach { (key,label,on) ->
            toggle(label,on) { checked ->
                if(!checked) { control.setPolicies(mapOf("unlocks" to mapOf(key to false)));render() }
                else if(control.tasks.isActive) { show("任务进行中","请先停止当前手机任务，再修改敏感操作权限。" );render() }
                else {
                    val hold=Button(this).apply {text="按住 1.5 秒开启"}
                    val dialog=AlertDialog.Builder(this).setTitle("允许：$label")
                        .setMessage("开启后模型可以操作这些内容，可能影响账号、权限或数据。请仅在需要时开启，用完关闭。")
                        .setView(hold).setNegativeButton("取消") {_,_->render()}.create()
                    val handler=android.os.Handler(mainLooper);
                    val allow=Runnable { if(alive && !control.tasks.isActive) {control.setPolicies(mapOf("unlocks" to mapOf(key to true)));dialog.dismiss();render()} }
                    hold.setOnTouchListener {_,event -> when(event.actionMasked) {
                        android.view.MotionEvent.ACTION_DOWN -> {if(event.deviceId>0 && event.flags and 3==0) handler.postDelayed(allow,1500)}
                        android.view.MotionEvent.ACTION_UP,android.view.MotionEvent.ACTION_CANCEL -> handler.removeCallbacks(allow)
                    };true }
                    dialog.setOnDismissListener {handler.removeCallbacks(allow)};dialog.show()
                }
            }
        }
        text("当前任务",21);text(Json.write(control.tasks.snapshot().toMap()))
        button("暂停 / 继续") { control.onPauseChanged(!control.tasks.isPaused);render() }
        button("停止手机操控任务") { control.stopTask("用户在设置中停止");render() }
        button("查看操作记录") { show("操作记录",Json.write(control.log.toMaps(300))) }
        button("返回 Codex") {startActivity(EntryRoutes.openApp(this));finish()}
        text("来源：ccch1mneyyy/dsh-Go，AGPL-3.0；相关第三方声明保留在源码与安装包中。",14)
    }
    private fun adb() {
        val form=LinearLayout(this).apply {orientation=LinearLayout.VERTICAL}
        val port=EditText(this).apply {hint="配对端口";inputType=2};form.addView(port)
        val code=EditText(this).apply {hint="六位配对码";inputType=18};form.addView(code)
        val connect=EditText(this).apply {hint="连接端口";inputType=2};form.addView(connect)
        AlertDialog.Builder(this).setTitle("无线调试：本机手动配对").setView(form).setNegativeButton("取消",null)
            .setPositiveButton("配对并连接") {_,_->val secret=code.text.toString();val pp=port.text.toString().toIntOrNull();val cp=connect.text.toString().toIntOrNull();code.setText("")
                if(pp!=null && cp!=null) work { control.background.adbPair(secret,pp);control.background.adbConnect(cp) {alive && control.isEnabled()};control.background.setBackgroundMode("adb") {alive && control.isEnabled()} }
            }.show()
    }
    private fun rules() {
        val p=control.policies();val form=LinearLayout(this).apply {orientation=LinearLayout.VERTICAL}
        val deny=EditText(this).apply {hint="禁止应用包名，每行一个";setText(p.denyPackages.joinToString("\n"))};form.addView(deny)
        val ask=EditText(this).apply {hint="每一步确认的应用包名，每行一个";setText(p.confirmEveryWritePackages.joinToString("\n"))};form.addView(ask)
        AlertDialog.Builder(this).setTitle("应用名单：修改后生效").setMessage("移除禁止名单中的应用会允许模型读取和操作它。")
            .setView(form).setNegativeButton("取消",null).setPositiveButton("保存") {_,_->
                control.setPolicies(mapOf("denyPackages" to deny.text.lines().filter{it.isNotBlank()},"confirmEveryWritePackages" to ask.text.lines().filter{it.isNotBlank()}));render()
            }.show()
    }
    private fun work(block: ()->Map<String,Any?>?) { if(busy)return;busy=true
        Thread { val result=try {block()}catch(e:Exception){mapOf("错误" to (e.message?:e.javaClass.simpleName))};runOnUiThread {busy=false;if(alive){render();if(result!=null)show("执行结果",Json.write(result))}} }.start()
    }
    private fun show(title:String,message:String) { AlertDialog.Builder(this).setTitle(title).setMessage(message).setPositiveButton("确定",null).show() }
    private fun text(value:String,size:Int=16) {body.addView(TextView(this).apply {text=value;textSize=size.toFloat();setPadding(0,12,0,12)})}
    private fun button(label:String,action:()->Unit){body.addView(Button(this).apply {text=label;setOnClickListener{action()}})}
    private fun toggle(label:String,on:Boolean,changed:(Boolean)->Unit) {body.addView(Switch(this).apply {text=label;textSize=17f;setPadding(0,16,0,16);isChecked=on;setOnCheckedChangeListener{_,v->changed(v)}})}
}
