package com.legogod.adbime;

/** 输入法服务与广播接收器之间的桥接状态（同一进程）。 */
final class ImeBridge {

    private static final Object LOCK = new Object();
    private static String pending;

    static volatile AdbImeService service;

    private ImeBridge() {
    }

    static void setPending(String text) {
        synchronized (LOCK) {
            pending = text;
        }
    }

    static String takePending() {
        synchronized (LOCK) {
            String value = pending;
            pending = null;
            return value;
        }
    }
}
