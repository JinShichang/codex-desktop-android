/*
 * Live Update permission and progress presentation adapted from Duck Detector Refactoring
 * (ScanProgressNotifier.kt / ScanNotificationPermissions.kt), revision ba8ea3c496a5348c977e87ce565c870a565fb5ee.
 * Copyright 2026 Duck Apps Contributor
 * Licensed under the Apache License, Version 2.0. See
 * third-party/duck-detector-live-updates/LICENSE.
 * Modified for Codex: framework APIs, indeterminate tasks, shared phone/runtime lifecycle.
 */
package com.ai.codex;

import android.app.Notification;
import android.app.NotificationManager;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.provider.Settings;

/** Requests Android Live Updates, including island presentation on supported ROMs. */
public final class LiveNotifications {
    public static final long SCROLL_MS = 2000;
    public static final int PHONE_ID = 5170;
    public static final String PHONE_CHANGED = "com.ai.codex.PHONE_LIVE_CHANGED";
    // Use the documented extra without linking the framework Builder setter,
    // which only became public in API 36.1. Older ROMs may ignore the request.
    private static final String REQUEST_PROMOTED_ONGOING = "android.requestPromotedOngoing";
    private LiveNotifications() { }
    public static boolean notificationsEnabled(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        return manager != null && manager.areNotificationsEnabled();
    }
    /** Re-read on every update so changes in system settings take effect without a restart. */
    public static boolean canPromote(Context context) {
        if (Build.VERSION.SDK_INT < 36) return false;
        try {
            if (!notificationsEnabled(context)) return false;
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            return manager != null && Api36.canPromote(manager);
        } catch (RuntimeException | LinkageError ignored) {
            return false;
        }
    }
    public static Intent settingsIntent(Context context) {
        if (Build.VERSION.SDK_INT >= 36) {
            Intent promotion = new Intent(Settings.ACTION_APP_NOTIFICATION_PROMOTION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, context.getPackageName());
            if (promotion.resolveActivity(context.getPackageManager()) != null) return promotion;
        }
        return new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE, context.getPackageName());
    }
    public static Notification.Builder apply(Context context, Notification.Builder builder, boolean active, String line, long frame) {
        builder.setOnlyAlertOnce(true).setAutoCancel(false).setLocalOnly(true);
        builder.getExtras().remove(REQUEST_PROMOTED_ONGOING);
        if (active) {
            builder.setOngoing(true).setCategory(Notification.CATEGORY_PROGRESS);
            builder.setStyle(new Notification.BigTextStyle().bigText(line)).setProgress(0, 0, true);
        }
        if (active && canPromote(context)) {
            try {
                Api36.apply(builder, line, frame);
            } catch (RuntimeException | LinkageError ignored) {
                // Optional Live Update APIs must never prevent a foreground
                // service from starting, including on partial OEM backports.
                builder.setStyle(new Notification.BigTextStyle().bigText(line)).setProgress(0, 0, true);
            }
        }
        return builder;
    }
    // Isolate newer framework types so older/partial ROMs can still load the
    // ordinary notification path. Linkage failures are caught by the caller.
    private static final class Api36 {
        static boolean canPromote(NotificationManager manager) {
            return manager.canPostPromotedNotifications();
        }
        static void apply(Notification.Builder builder, String line, long frame) {
            builder.setShortCriticalText(LiveNotificationText.chip(line, frame));
            // Agent tasks have no reliable total; never invent a completion percentage.
            builder.setStyle(new Notification.ProgressStyle().setProgressIndeterminate(true));
            builder.getExtras().putBoolean(REQUEST_PROMOTED_ONGOING, true);
        }
    }
    /** Runtime runs in a separate process; read OS-owned state rather than a static flag. */
    public static boolean phoneIsActive(Context context) {
        try {
            for (android.service.notification.StatusBarNotification posted : context.getSystemService(NotificationManager.class).getActiveNotifications()) {
                if (posted.getId() == PHONE_ID && posted.getTag() == null && posted.getPackageName().equals(context.getPackageName())) {
                    Notification n = posted.getNotification();
                    long timeout = n.getTimeoutAfter();
                    if ((n.flags & Notification.FLAG_ONGOING_EVENT) != 0 &&
                        (timeout <= 0 || System.currentTimeMillis() - posted.getPostTime() < timeout)) return true;
                }
            }
        } catch (RuntimeException ignored) { }
        return false;
    }
    public static void phoneChanged(Context context) {
        context.sendBroadcast(new Intent(PHONE_CHANGED).setPackage(context.getPackageName()));
    }
}
