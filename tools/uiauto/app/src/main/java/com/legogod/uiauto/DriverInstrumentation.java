package com.legogod.uiauto;

import android.app.Activity;
import android.app.Instrumentation;
import android.accessibilityservice.AccessibilityService;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Base64;
import android.util.Log;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/**
 * 真机 E2E 的 UiAutomation 驱动（测试工具，不属于 APP 产品代码）。
 *
 * 用法示例：
 *   adb shell am instrument -w -e action dump com.legogod.uiauto/.DriverInstrumentation
 *   adb shell am instrument -w -e action clickText -e text 测试连接 com.legogod.uiauto/.DriverInstrumentation
 * 动作：dump / clickText / clickDesc / clickPoint / tap / swipe / back / home / recents /
 *       setText / waitText / screen / screenshot
 * 结果：写到 /sdcard/Android/data/com.legogod.uiauto/files/result.txt 供 adb pull 取证。
 */
public class DriverInstrumentation extends Instrumentation {

    private static final String TAG = "LegoUIAuto";
    private Bundle args = new Bundle();

    @Override
    public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        if (arguments != null) {
            args = arguments;
        }
        start();
    }

    @Override
    public void start() {
        Thread worker = new Thread(this::runAction, "uiauto-worker");
        worker.start();
    }

    private void runAction() {
        String action = arg("action", "dump");
        String result;
        try {
            result = dispatch(action);
        } catch (Throwable t) {
            Log.e(TAG, "action failed: " + action, t);
            result = "ERR|" + action + "|" + t.getClass().getSimpleName() + ": " + t.getMessage();
        }
        writeResult(result);
        Bundle bundle = new Bundle();
        bundle.putString("result", truncate(result, 2000));
        finish(Activity.RESULT_OK, bundle);
    }

    private String dispatch(String action) {
        switch (action) {
            case "dump":
                return "OK|dump|" + dumpTree();
            case "dumpall":
                return "OK|dumpall|" + dumpTreeAll();
            case "focusText":
                return focusEditable(argInt("index", 0));
            case "setTextIndex":
                return setTextOnEditableIndex(argInt("index", 0), argText());
            case "tapText":
                return tapNodeBy(true, argText(), argBool("exact", false));
            case "clickPointNode":
                return clickPointNode(argInt("x", 0), argInt("y", 0));
            case "clickTextPoint":
                return clickTextPoint(argText());
            case "scroll":
                return scroll(arg("direction", "forward"));
            case "scrollIndex":
                return scrollIndex(argInt("index", 0), arg("direction", "forward"));
            case "screen": {
                android.util.DisplayMetrics metrics = getContext().getResources().getDisplayMetrics();
                return "OK|screen|" + metrics.widthPixels + "x" + metrics.heightPixels;
            }
            case "clickText":
                return clickNodeBy(true, argText(), argBool("exact", false));
            case "clickDesc":
                return clickNodeBy(false, argText(), argBool("exact", false));
            case "clickPoint":
                return tap(argInt("x", 0), argInt("y", 0));
            case "tap":
                return tap(argInt("x", 0), argInt("y", 0));
            case "swipe":
                return swipe(argInt("x1", 540), argInt("y1", 1500),
                        argInt("x2", 540), argInt("y2", 700), argInt("duration", 300));
            case "back":
                return globalAction(AccessibilityService.GLOBAL_ACTION_BACK);
            case "home":
                return globalAction(AccessibilityService.GLOBAL_ACTION_HOME);
            case "recents":
                return globalAction(AccessibilityService.GLOBAL_ACTION_RECENTS);
            case "setText":
                return setTextOnEditable(argText());
            case "waitText":
                return waitText(argText(), argInt("timeoutMs", 15000));
            case "screenshot":
                return screenshot(arg("name", "shot.png"));
            case "clipboard":
                return setClipboard(argText());
            case "pressKey":
                return pressKey(argInt("key", KeyEvent.KEYCODE_BACK));
            default:
                return "ERR|unknown_action|" + action;
        }
    }

    // ---------- 参数 ----------
    private String arg(String key, String def) {
        String value = args.getString(key);
        return value == null ? def : value;
    }

    /** 读取文本参数：b64=1 时按 base64(UTF-8) 解码，避免 adb shell 对中文/空格的分词与编码问题。 */
    private String argText() {
        String value = args.getString("text");
        if (value == null) {
            return "";
        }
        if (argBool("b64", false)) {
            try {
                return new String(Base64.decode(value, Base64.NO_WRAP), StandardCharsets.UTF_8);
            } catch (Throwable t) {
                return value;
            }
        }
        return value;
    }

    private int argInt(String key, int def) {
        String value = args.getString(key);
        if (value == null || value.isEmpty()) {
            return def;
        }
        try {
            return Integer.parseInt(value.trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }

    private boolean argBool(String key, boolean def) {
        String value = args.getString(key);
        if (value == null) {
            return def;
        }
        return "1".equals(value) || "true".equalsIgnoreCase(value);
    }

    // ---------- 节点遍历 ----------
    private AccessibilityNodeInfo root() {
        try {
            getUiAutomation().waitForIdle(200, 2000);
        } catch (Throwable ignored) {
            // waitForIdle 在部分系统版本可能不支持：继续直接取根节点
        }
        for (int i = 0; i < 12; i++) {
            AccessibilityNodeInfo node = getUiAutomation().getRootInActiveWindow();
            if (node != null) {
                return node;
            }
            SystemClock.sleep(300);
        }
        return null;
    }

    private List<AccessibilityNodeInfo> flatten(AccessibilityNodeInfo root) {
        List<AccessibilityNodeInfo> out = new ArrayList<>();
        if (root == null) {
            return out;
        }
        collect(root, out, 0);
        return out;
    }

    private void collect(AccessibilityNodeInfo node, List<AccessibilityNodeInfo> out, int depth) {
        if (node == null || depth > 40) {
            return;
        }
        out.add(node);
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                collect(child, out, depth + 1);
            }
        }
    }

    private String dumpTree() {
        StringBuilder sb = new StringBuilder();
        for (AccessibilityNodeInfo node : flatten(root())) {
            CharSequence text = node.getText();
            CharSequence desc = node.getContentDescription();
            if ((text == null || text.length() == 0) && (desc == null || desc.length() == 0)) {
                continue;
            }
            Rect rect = new Rect();
            node.getBoundsInScreen(rect);
            String cls = node.getClassName() == null ? "" : node.getClassName().toString();
            sb.append("NODE")
                    .append("|class=").append(cls)
                    .append("|text=").append(safe(text))
                    .append("|desc=").append(safe(desc))
                    .append("|editable=").append(node.isEditable())
                    .append("|clickable=").append(node.isClickable())
                    .append("|enabled=").append(node.isEnabled())
                    .append("|bounds=").append(rect.left).append(",").append(rect.top)
                    .append(",").append(rect.right).append(",").append(rect.bottom)
                    .append("|");
        }
        return sb.toString();
    }

    private String safe(CharSequence text) {
        if (text == null) {
            return "";
        }
        return text.toString().replace("|", "/").replace("\n", " ");
    }

    /** 全量节点（包含无文本节点），重点标注 editable/focusable/actions，供文本输入定位。 */
    private String dumpTreeAll() {
        StringBuilder sb = new StringBuilder();
        int index = 0;
        for (AccessibilityNodeInfo node : flatten(root())) {
            Rect rect = new Rect();
            node.getBoundsInScreen(rect);
            sb.append("NODE")
                    .append("|i=").append(index++)
                    .append("|class=").append(node.getClassName() == null ? "" : node.getClassName())
                    .append("|text=").append(safe(node.getText()))
                    .append("|desc=").append(safe(node.getContentDescription()))
                    .append("|editable=").append(node.isEditable())
                    .append("|clickable=").append(node.isClickable())
                    .append("|focusable=").append(node.isFocusable())
                    .append("|actions=").append(node.getActions())
                    .append("|scrollable=").append(node.isScrollable())
                    .append("|bounds=").append(rect.left).append(",").append(rect.top)
                    .append(",").append(rect.right).append(",").append(rect.bottom)
                    .append("|");
        }
        return sb.toString();
    }

    /** 聚焦第 n 个可编辑节点（Flutter 文本框暴露 editable 语义节点）。 */
    private String focusEditable(int index) {
        List<AccessibilityNodeInfo> editables = new ArrayList<>();
        for (AccessibilityNodeInfo node : flatten(root())) {
            if (node.isEditable()) {
                editables.add(node);
            }
        }
        if (editables.isEmpty()) {
            return "NB|no_editable_node";
        }
        if (index < 0 || index >= editables.size()) {
            return "NB|editable_index_out_of_range|" + editables.size();
        }
        AccessibilityNodeInfo target = editables.get(index);
        boolean focused = target.performAction(AccessibilityNodeInfo.ACTION_FOCUS);
        boolean clicked = target.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        Rect rect = new Rect();
        target.getBoundsInScreen(rect);
        SystemClock.sleep(500);
        return "OK|focusText|index=" + index + "|focus=" + focused + "|click=" + clicked
                + "|bounds=" + rect.left + "," + rect.top + "," + rect.right + "," + rect.bottom;
    }

    /** 对第 n 个可编辑节点执行 ACTION_SET_TEXT。 */
    private String setTextOnEditableIndex(int index, String text) {
        List<AccessibilityNodeInfo> editables = new ArrayList<>();
        for (AccessibilityNodeInfo node : flatten(root())) {
            if (node.isEditable()) {
                editables.add(node);
            }
        }
        if (editables.isEmpty()) {
            return "NB|no_editable_node";
        }
        if (index < 0 || index >= editables.size()) {
            return "NB|editable_index_out_of_range|" + editables.size();
        }
        Bundle bundle = new Bundle();
        bundle.putCharSequence(
                AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        boolean ok = editables.get(index)
                .performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, bundle);
        SystemClock.sleep(400);
        return "OK|setTextIndex|index=" + index + "|accessibility=" + ok + "|len=" + text.length();
    }

    /** 按文本定位节点中心并执行无障碍点击（不需要 INJECT_EVENTS 权限）。 */
    private String tapNodeBy(boolean useText, String target, boolean exact) {
        if (target == null || target.isEmpty()) {
            return "ERR|empty_text";
        }
        AccessibilityNodeInfo found = null;
        for (AccessibilityNodeInfo node : flatten(root())) {
            CharSequence value = useText ? node.getText() : node.getContentDescription();
            if (value == null) {
                continue;
            }
            String text = value.toString();
            boolean matched = exact ? text.equals(target) : text.contains(target);
            if (matched) {
                found = node;
                break;
            }
        }
        if (found == null) {
            return "NB|not_found|" + target;
        }
        return performClickWithFallback(found, target);
    }

    /**
     * 在指定坐标找到可点击节点（取包含该点、面积最小的可点击节点）并执行无障碍点击。
     * 设置类列表行常由不可点击的 TextView + 可点击的父容器组成，这里按坐标匹配容器。
     */
    private String clickPointNode(int x, int y) {
        AccessibilityNodeInfo best = null;
        long bestArea = Long.MAX_VALUE;
        for (AccessibilityNodeInfo node : flatten(root())) {
            if (!node.isClickable()) {
                continue;
            }
            Rect rect = new Rect();
            node.getBoundsInScreen(rect);
            if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
                continue;
            }
            long area = (long) (rect.right - rect.left) * (rect.bottom - rect.top);
            if (area < bestArea) {
                bestArea = area;
                best = node;
            }
        }
        if (best == null) {
            return "NB|no_clickable_node_at|" + x + "," + y;
        }
        boolean ok = best.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        SystemClock.sleep(500);
        return "OK|clickPointNode|" + x + "," + y + "|accessibility=" + ok
                + "|area=" + bestArea;
    }

    /** 按文本找到节点，再用其中心点匹配可点击容器并点击。 */
    private String clickTextPoint(String target) {
        if (target == null || target.isEmpty()) {
            return "ERR|empty_text";
        }
        AccessibilityNodeInfo found = null;
        for (AccessibilityNodeInfo node : flatten(root())) {
            CharSequence text = node.getText();
            CharSequence desc = node.getContentDescription();
            if ((text != null && text.toString().contains(target))
                    || (desc != null && desc.toString().contains(target))) {
                found = node;
                break;
            }
        }
        if (found == null) {
            return "NB|not_found|" + target;
        }
        Rect rect = new Rect();
        found.getBoundsInScreen(rect);
        return clickPointNode(rect.centerX(), rect.centerY());
    }

    /** 对展开树中第 n 个节点执行滚动（用于精确定位页面内列表）。 */
    private String scrollIndex(int index, String direction) {
        List<AccessibilityNodeInfo> nodes = flatten(root());
        if (index < 0 || index >= nodes.size()) {
            return "NB|index_out_of_range|" + nodes.size();
        }
        AccessibilityNodeInfo node = nodes.get(index);
        int action = "backward".equalsIgnoreCase(direction)
                ? AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
                : AccessibilityNodeInfo.ACTION_SCROLL_FORWARD;
        boolean ok = node.performAction(action);
        SystemClock.sleep(500);
        return "OK|scrollIndex|" + index + "|" + direction + "|scrollable=" + node.isScrollable()
                + "|accessibility=" + ok;
    }

    /** 滚动第一个可滚动节点（用于长页面）。 */
    private String scroll(String direction) {        for (AccessibilityNodeInfo node : flatten(root())) {
            if (!node.isScrollable()) {
                continue;
            }
            int action = "backward".equalsIgnoreCase(direction)
                    ? AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
                    : AccessibilityNodeInfo.ACTION_SCROLL_FORWARD;
            boolean ok = node.performAction(action);
            SystemClock.sleep(500);
            return "OK|scroll|" + direction + "|accessibility=" + ok;
        }
        return "NB|no_scrollable_node";
    }

    // ---------- 操作 ----------
    private String clickNodeBy(boolean useText, String target, boolean exact) {
        if (target == null || target.isEmpty()) {
            return "ERR|empty_text";
        }
        AccessibilityNodeInfo found = null;
        for (AccessibilityNodeInfo node : flatten(root())) {
            CharSequence value = useText ? node.getText() : node.getContentDescription();
            if (value == null) {
                continue;
            }
            String text = value.toString();
            boolean matched = exact ? text.equals(target) : text.contains(target);
            if (matched) {
                found = node;
                break;
            }
        }
        if (found == null) {
            return "NB|not_found|" + target;
        }
        return performClickWithFallback(found, target);
    }

    /** 优先点击节点自身；不可点击则沿父链找可点击祖先（设置类列表行常见）。 */
    private String performClickWithFallback(AccessibilityNodeInfo node, String label) {
        AccessibilityNodeInfo target = node;
        int depth = 0;
        while (target != null && !target.isClickable() && depth < 8) {
            target = target.getParent();
            depth++;
        }
        Rect rect = new Rect();
        node.getBoundsInScreen(rect);
        boolean ok = target != null && target.isClickable()
                && target.performAction(AccessibilityNodeInfo.ACTION_CLICK);
        SystemClock.sleep(500);
        return "OK|click|" + label + "|bounds=" + rect.left + "," + rect.top + ","
                + rect.right + "," + rect.bottom + "|accessibility=" + ok
                + "|parentDepth=" + depth;
    }

    private String tap(int x, int y) {
        long downTime = SystemClock.uptimeMillis();
        MotionEvent down = MotionEvent.obtain(downTime, downTime, MotionEvent.ACTION_DOWN, x, y, 0);
        MotionEvent up = MotionEvent.obtain(downTime, downTime + 80, MotionEvent.ACTION_UP, x, y, 0);
        boolean okDown = getUiAutomation().injectInputEvent(down, true);
        boolean okUp = getUiAutomation().injectInputEvent(up, true);
        down.recycle();
        up.recycle();
        SystemClock.sleep(300);
        return "OK|tap|" + x + "," + y + "|" + okDown + "/" + okUp;
    }

    private String swipe(int x1, int y1, int x2, int y2, int duration) {
        long downTime = SystemClock.uptimeMillis();
        int steps = 12;
        List<MotionEvent> events = new ArrayList<>();
        events.add(MotionEvent.obtain(downTime, downTime, MotionEvent.ACTION_DOWN, x1, y1, 0));
        for (int i = 1; i <= steps; i++) {
            float ratio = i / (float) steps;
            long t = downTime + (long) (duration * ratio);
            float x = x1 + (x2 - x1) * ratio;
            float y = y1 + (y2 - y1) * ratio;
            events.add(MotionEvent.obtain(downTime, t, MotionEvent.ACTION_MOVE, x, y, 0));
        }
        events.add(MotionEvent.obtain(downTime, downTime + duration,
                MotionEvent.ACTION_UP, x2, y2, 0));
        boolean ok = true;
        for (MotionEvent event : events) {
            ok &= getUiAutomation().injectInputEvent(event, true);
            event.recycle();
            SystemClock.sleep(10);
        }
        SystemClock.sleep(300);
        return "OK|swipe|" + x1 + "," + y1 + "," + x2 + "," + y2 + "|" + ok;
    }

    private String globalAction(int action) {
        boolean ok = getUiAutomation().performGlobalAction(action);
        SystemClock.sleep(600);
        return "OK|globalAction|" + action + "|" + ok;
    }

    private String pressKey(int keyCode) {
        long now = SystemClock.uptimeMillis();
        KeyEvent down = new KeyEvent(now, now, KeyEvent.ACTION_DOWN, keyCode, 0);
        KeyEvent up = new KeyEvent(now, now + 60, KeyEvent.ACTION_UP, keyCode, 0);
        boolean ok = getUiAutomation().injectInputEvent(down, true);
        ok &= getUiAutomation().injectInputEvent(up, true);
        return "OK|pressKey|" + keyCode + "|" + ok;
    }

    /** 通过无障碍编辑操作给输入框设置文本（Flutter 若支持 SetText 语义可用）。 */
    private String setTextOnEditable(String text) {
        for (AccessibilityNodeInfo node : flatten(root())) {
            if (!node.isEditable()) {
                continue;
            }
            Bundle bundle = new Bundle();
            bundle.putCharSequence(
                    AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
            boolean ok = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, bundle);
            SystemClock.sleep(300);
            return "OK|setText|accessibility=" + ok;
        }
        return "NB|no_editable_node";
    }

    private String waitText(String target, int timeoutMs) {
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            for (AccessibilityNodeInfo node : flatten(root())) {
                CharSequence text = node.getText();
                CharSequence desc = node.getContentDescription();
                if ((text != null && text.toString().contains(target))
                        || (desc != null && desc.toString().contains(target))) {
                    return "OK|waitText|" + target;
                }
            }
            SystemClock.sleep(400);
        }
        return "NB|timeout|" + target;
    }

    /** 无障碍截图（保底取证方式；adb screencap 也可用）。 */
    private String screenshot(String name) {
        try {
            Bitmap bitmap = getUiAutomation().takeScreenshot();
            if (bitmap == null) {
                return "ERR|screenshot_null";
            }
            File dir = getContext().getExternalFilesDir(null);
            if (dir == null) {
                dir = getContext().getFilesDir();
            }
            if (!dir.exists()) {
                dir.mkdirs();
            }
            File file = new File(dir, name);
            try (FileOutputStream out = new FileOutputStream(file)) {
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, out);
            }
            return "OK|screenshot|" + file.getAbsolutePath();
        } catch (Throwable t) {
            return "ERR|screenshot|" + t.getMessage();
        }
    }

    private String setClipboard(String text) {
        ClipboardManager manager =
                (ClipboardManager) getContext().getSystemService(Context.CLIPBOARD_SERVICE);
        manager.setPrimaryClip(ClipData.newPlainText("legogod-e2e", text));
        return "OK|clipboard|" + text.length();
    }

    // ---------- 结果落盘 ----------
    private void writeResult(String result) {
        // 主通道：通过 UiAutomation 的 shell 身份写入 /data/local/tmp（adb 可直接 pull）。
        try {
            android.os.ParcelFileDescriptor pfd =
                    getUiAutomation().executeShellCommand("sh -c 'cat > /data/local/tmp/uiauto_result.txt'");
            try (java.io.FileOutputStream out =
                         new java.io.FileOutputStream(pfd.getFileDescriptor())) {
                out.write(result.getBytes("UTF-8"));
                out.flush();
            } finally {
                try {
                    pfd.close();
                } catch (Throwable ignored) {
                    // 关闭失败不影响结果
                }
            }
            Log.i(TAG, "result -> /data/local/tmp/uiauto_result.txt");
        } catch (Throwable t) {
            Log.e(TAG, "shell write result failed", t);
        }
        // 兜底通道：logcat（每行 3000 字以内）。
        if (result != null) {
            int chunk = 3000;
            for (int i = 0; i < result.length(); i += chunk) {
                Log.i(TAG, "RESULT|" + result.substring(i, Math.min(result.length(), i + chunk)));
            }
        }
    }

    private String truncate(String text, int max) {
        if (text == null) {
            return "";
        }
        return text.length() <= max ? text : text.substring(0, max) + "...";
    }
}
