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
    private LiveNotifications() { }
    public static boolean notificationsEnabled(Context context) {
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        return manager != null && manager.areNotificationsEnabled();
    }
    /** Re-read on every update so changes in system settings take effect without a restart. */
    public static boolean canPromote(Context context) {
        if (Build.VERSION.SDK_INT < 36 || !notificationsEnabled(context)) return false;
        try {
            NotificationManager manager = context.getSystemService(NotificationManager.class);
            return manager != null && manager.canPostPromotedNotifications();
        } catch (RuntimeException ignored) {
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
        if (active) {
            builder.setOngoing(true).setCategory(Notification.CATEGORY_PROGRESS);
            builder.setStyle(new Notification.BigTextStyle().bigText(line)).setProgress(0, 0, true);
        }
        if (Build.VERSION.SDK_INT >= 36) {
            boolean promote = active && canPromote(context);
            builder.setRequestPromotedOngoing(promote)
                .setShortCriticalText(promote ? LiveNotificationText.chip(line, frame) : null);
            if (promote) {
                // Agent tasks have no reliable total; never invent a completion percentage.
                builder.setStyle(new Notification.ProgressStyle().setProgressIndeterminate(true));
            }
        }
        return builder;
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
