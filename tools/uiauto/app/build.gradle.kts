// 测试工具：真机 E2E 的 UiAutomation 驱动（无第三方依赖，仅 Android Framework）。
// 通过自定义 Instrumentation 在设备上执行 UI 查询/点击/返回等操作，绕过 MIUI 对
// `adb shell input` 的限制；结果写入应用外部目录供 adb pull 取证。
//
// 签名：不声明任何 signingConfigs，仓库内不出现密钥库路径与口令。
// debug 构建使用 AGP 默认 debug 签名（本机 ~/.android/debug.keystore，自动生成）；
// release 构建保持 AGP 默认行为（不签名），测试安装请使用：
//   gradle -p tools/uiauto assembleDebug
plugins {
    id("com.android.application")
}

android {
    namespace = "com.legogod.uiauto"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.legogod.uiauto"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
