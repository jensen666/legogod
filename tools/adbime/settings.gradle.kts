// 测试工具：极简 ADB 输入法（仅用于真机 E2E 注入中文文本，不属于 APP 产品代码）。
// 通过 shell 广播把 UTF-8（base64）文本提交到当前输入框，模拟真实输入法输入。
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "legogod-adb-ime"
include(":app")
