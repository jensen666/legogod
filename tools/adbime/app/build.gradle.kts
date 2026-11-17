// ADB 测试输入法模块：不依赖任何第三方库，仅用 Android Framework API。
plugins {
    id("com.android.application")
}

android {
    namespace = "com.legogod.adbime"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.legogod.adbime"
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
