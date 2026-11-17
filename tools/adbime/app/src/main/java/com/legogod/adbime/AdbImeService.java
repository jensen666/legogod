package com.legogod.adbime;

import android.inputmethodservice.InputMethodService;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;
import android.widget.TextView;

/**
 * 极简输入法：没有软键盘 UI，只负责把 shell 广播来的文本提交到当前输入框。
 * 仅用于真机 E2E 自动化注入中文（Android 的 `input text` 不支持非 ASCII）。
 */
public class AdbImeService extends InputMethodService {

    private static final String TAG = "AdbIme";
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    /** 当前是否有用户正在编辑的输入连接。 */
    boolean hasInput() {
        return getCurrentInputConnection() != null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        ImeBridge.service = this;
    }

    @Override
    public void onDestroy() {
        if (ImeBridge.service == this) {
            ImeBridge.service = null;
        }
        super.onDestroy();
    }

    @Override
    public View onCreateInputView() {
        // 不显示软键盘：用一个极小的占位视图，避免系统键盘遮挡页面。
        TextView placeholder = new TextView(getApplicationContext());
        placeholder.setLayoutParams(new ViewGroup.LayoutParams(0, 0));
        return placeholder;
    }

    @Override
    public void onStartInputView(EditorInfo info, boolean restarting) {
        super.onStartInputView(info, restarting);
        // 输入框获得焦点后，如果广播早于输入连接建立，补提交。
        String pending = ImeBridge.takePending();
        if (pending != null) {
            commitText(pending);
        }
    }

    /** 把文本提交到当前输入连接（在主线程执行）。 */
    void commitText(String text) {
        mainHandler.post(() -> {
            InputConnection ic = getCurrentInputConnection();
            if (ic == null) {
                ImeBridge.setPending(text);
                return;
            }
            ic.commitText(text, 1);
        });
    }

    /** 删除光标前 count 个字符（用于清空输入框）。 */
    void deleteBackward(int count) {
        mainHandler.post(() -> {
            InputConnection ic = getCurrentInputConnection();
            if (ic == null || count <= 0) {
                return;
            }
            ic.deleteSurroundingText(count, 0);
        });
    }
}
