// 根构建脚本：只有 app 模块；声明仓库以便解析 AGP/aapt2 等构建依赖。
plugins {
    id("com.android.application") version "8.11.1" apply false
}

allprojects {
    repositories {
        google()
        mavenCentral()
    }
}
