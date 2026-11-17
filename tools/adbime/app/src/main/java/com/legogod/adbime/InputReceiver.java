package com.legogod.adbime;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Base64;

import java.nio.charset.StandardCharsets;

/**
 * 接收 shell 广播：
 *   adb shell am broadcast -a com.legogod.adbime.INPUT --es msg <base64(utf8)>
 *   adb shell am broadcast -a com.legogod.adbime.DELETE --ei count <n>
 */
public class InputReceiver extends BroadcastReceiver {

    @Override
    public void onReceive(Context context, Intent intent) {
        if (intent == null) {
            return;
        }
        String action = intent.getAction();
        AdbImeService service = ImeBridge.service;
        if ("com.legogod.adbime.DELETE".equals(action)) {
            int count = intent.getIntExtra("count", 0);
            if (service != null) {
                service.deleteBackward(count);
            }
            return;
        }
        if (!"com.legogod.adbime.INPUT".equals(action)) {
            return;
        }
        String encoded = intent.getStringExtra("msg");
        if (encoded == null || encoded.isEmpty()) {
            return;
        }
        String text;
        try {
            text = new String(Base64.decode(encoded, Base64.NO_WRAP), StandardCharsets.UTF_8);
        } catch (IllegalArgumentException e) {
            return;
        }
        if (service == null) {
            ImeBridge.setPending(text);
            return;
        }
        service.commitText(text);
    }
}
