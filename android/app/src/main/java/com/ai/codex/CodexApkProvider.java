package com.ai.codex;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.ParcelFileDescriptor;
import android.provider.OpenableColumns;
import java.io.File;
import java.io.FileNotFoundException;
import java.util.ArrayList;
import java.util.List;

/** Exposes only the shared APK explicitly handed to Android's installer. */
public final class CodexApkProvider extends ContentProvider {
    static final String MIME_TYPE = "application/vnd.android.package-archive";

    static Uri uri(Context context, String path) {
        return new Uri.Builder().scheme("content").authority(context.getPackageName() + ".apk")
            .appendPath(path).build();
    }

    private static String path(Uri uri) {
        List<String> segments = uri.getPathSegments();
        if (segments.size() != 1) throw new IllegalArgumentException("invalid_apk_uri");
        String path = segments.get(0);
        DeviceFilePolicy.requireSharedApk(path);
        return path;
    }

    @Override public boolean onCreate() { return true; }
    @Override public String getType(Uri uri) { return MIME_TYPE; }

    @Override public ParcelFileDescriptor openFile(Uri uri, String mode) throws FileNotFoundException {
        if (!"r".equals(mode)) throw new FileNotFoundException("read_only_apk");
        try {
            return CodexDeviceSharedFiles.openApk(path(uri));
        } catch (Exception failure) {
            throw new FileNotFoundException("apk_unavailable");
        }
    }

    @Override public Cursor query(Uri uri, String[] projection, String selection, String[] selectionArgs,
            String sortOrder) {
        String[] requested = projection == null
            ? new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE} : projection;
        List<String> columns = new ArrayList<>();
        for (String column : requested) {
            if (OpenableColumns.DISPLAY_NAME.equals(column) || OpenableColumns.SIZE.equals(column))
                columns.add(column);
        }
        MatrixCursor result = new MatrixCursor(columns.toArray(new String[0]), 1);
        try (ParcelFileDescriptor file = openFile(uri, "r")) {
            String name = new File(path(uri)).getName();
            long size = CodexDeviceSharedFiles.size(file);
            MatrixCursor.RowBuilder row = result.newRow();
            for (String column : columns) {
                if (OpenableColumns.DISPLAY_NAME.equals(column)) row.add(name);
                else row.add(size);
            }
        } catch (Exception ignored) {
            // A file removed after the request has no metadata.
        }
        return result;
    }

    @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
    @Override public int update(Uri uri, ContentValues values, String where, String[] args) { throw new UnsupportedOperationException(); }
    @Override public int delete(Uri uri, String where, String[] args) { throw new UnsupportedOperationException(); }
}
