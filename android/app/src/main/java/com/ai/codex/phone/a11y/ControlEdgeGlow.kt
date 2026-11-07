package com.ai.codex.phone.a11y

import android.accessibilityservice.AccessibilityService
import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.RectF
import android.graphics.SweepGradient
import android.os.Build
import android.os.SystemClock
import android.util.Log
import android.view.Gravity
import android.view.RoundedCorner
import android.view.View
import android.view.WindowInsets
import android.view.WindowManager

/** Decorative accessibility window. It never accepts focus, input or accessibility actions. */
internal class ControlEdgeGlow(private val service: AccessibilityService) {
    private val wm = service.getSystemService(WindowManager::class.java)
    private var view: EdgeView? = null
    private var captureHidden = false
    private var destroyed = false

    val attached: Boolean get() = view?.isAttachedToWindow == true

    fun setActive(active: Boolean) {
        if (!active || destroyed) {
            remove()
            return
        }
        if (view != null) return
        val edge = EdgeView(service).apply {
            visibility = if (captureHidden) View.INVISIBLE else View.VISIBLE
        }
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.LEFT
            title = "Codex phone control glow"
            softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_NOTHING
            setFitInsetsTypes(0)
            layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
        }
        try {
            wm.addView(edge, params)
            view = edge
        } catch (error: Exception) {
            // A visual effect must never prevent pause, stop, screenshots or phone control.
            Log.w("CodexEdgeGlow", "Edge effect unavailable", error)
        }
    }

    fun hideForCapture(hidden: Boolean) {
        captureHidden = hidden
        view?.visibility = if (hidden) View.INVISIBLE else View.VISIBLE
    }

    fun refreshGeometry() { view?.refreshGeometry() }

    fun destroy() {
        destroyed = true
        remove()
    }

    private fun remove() {
        val old = view ?: return
        view = null
        runCatching { wm.removeViewImmediate(old) }
    }

    private class EdgeView(context: Context) : View(context) {
        private val density = resources.displayMetrics.density
        private val contour = Path()
        private val bounds = RectF()
        private val rotation = Matrix()
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeJoin = Paint.Join.ROUND
        }
        private var gradient: SweepGradient? = null
        private var insets: WindowInsets? = null
        private val widths = floatArrayOf(25f, 16f, 9f, 4f, 1.7f)
        private val alphas = intArrayOf(8, 15, 32, 86, 232)

        init {
            importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
            isClickable = false
            isFocusable = false
            setWillNotDraw(false)
            setOnApplyWindowInsetsListener { _, value ->
                insets = value
                rebuildContour()
                value
            }
        }

        override fun onAttachedToWindow() {
            super.onAttachedToWindow()
            requestApplyInsets()
        }

        override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
            super.onSizeChanged(w, h, oldw, oldh)
            gradient = SweepGradient(w / 2f, h / 2f, intArrayOf(
                Color.rgb(77, 216, 255), Color.rgb(112, 131, 255),
                Color.rgb(178, 113, 255), Color.rgb(245, 145, 213), Color.rgb(77, 216, 255),
            ), null)
            rebuildContour()
        }

        fun refreshGeometry() {
            requestApplyInsets()
            rebuildContour()
        }

        private fun fallbackRadius(top: Boolean): Float {
            // OEM resources are in physical pixels, unlike a guessed per-device dp radius.
            for (name in listOf(if (top) "rounded_corner_radius_top" else "rounded_corner_radius_bottom", "rounded_corner_radius")) {
                val id = resources.getIdentifier(name, "dimen", "android")
                if (id != 0) {
                    val value = resources.getDimension(id)
                    if (value > 0f || name == "rounded_corner_radius") return value
                }
            }
            return minOf(28f * density, minOf(width, height) * 0.1f)
        }

        private fun radius(position: Int, top: Boolean): Float {
            if (Build.VERSION.SDK_INT >= 31) {
                (insets ?: rootWindowInsets)?.getRoundedCorner(position)?.let { return it.radius.toFloat() }
            }
            return fallbackRadius(top)
        }

        private fun rebuildContour() {
            if (width <= 0 || height <= 0) return
            val inset = 1.5f * density
            bounds.set(inset, inset, width - inset, height - inset)
            val limit = minOf(bounds.width(), bounds.height()).coerceAtLeast(0f) / 2f
            val radii = floatArrayOf(
                radius(RoundedCorner.POSITION_TOP_LEFT, true),
                radius(RoundedCorner.POSITION_TOP_RIGHT, true),
                radius(RoundedCorner.POSITION_BOTTOM_RIGHT, false),
                radius(RoundedCorner.POSITION_BOTTOM_LEFT, false),
            ).map { (it - inset).coerceIn(0f, limit) }
            contour.reset()
            contour.addRoundRect(bounds, floatArrayOf(
                radii[0], radii[0], radii[1], radii[1], radii[2], radii[2], radii[3], radii[3],
            ), Path.Direction.CW)
            invalidate()
        }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val shader = gradient ?: return
            val animate = ValueAnimator.areAnimatorsEnabled()
            val phase = if (animate) (SystemClock.uptimeMillis() % 9_000L) / 9_000f else 0f
            rotation.setRotate(phase * 360f, width / 2f, height / 2f)
            shader.setLocalMatrix(rotation)
            paint.shader = shader
            // Layered hardware strokes make a soft halo without a full-screen software blur.
            for (index in widths.indices) {
                paint.strokeWidth = widths[index] * density
                paint.alpha = alphas[index]
                canvas.drawPath(contour, paint)
            }
            if (animate && isShown) postInvalidateDelayed(40L)
        }

        override fun onVisibilityChanged(changedView: View, visibility: Int) {
            super.onVisibilityChanged(changedView, visibility)
            if (visibility == VISIBLE) invalidate()
        }
    }
}
