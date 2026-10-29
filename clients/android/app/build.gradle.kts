plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

// The release upload key lives outside the repository (scripts/make-upload-key.sh puts it
// in ~/.ira-android). scripts/build-release.sh reads its password from the macOS Keychain
// and passes all four values in the environment. Without them, release builds are unsigned.
val uploadStore: String? = System.getenv("IRA_UPLOAD_STORE_FILE")
val uploadStorePassword: String? = System.getenv("IRA_UPLOAD_STORE_PASSWORD")
val uploadKeyAlias: String? = System.getenv("IRA_UPLOAD_KEY_ALIAS")
val uploadKeyPassword: String? = System.getenv("IRA_UPLOAD_KEY_PASSWORD")
val canSign = listOf(uploadStore, uploadStorePassword, uploadKeyAlias, uploadKeyPassword).all {
    !it.isNullOrBlank()
}

android {
    namespace = "io.github.helloupendra.ira"
    compileSdk = 37

    defaultConfig {
        applicationId = "io.github.helloupendra.ira"
        minSdk = 29
        targetSdk = 37
        versionCode = 3
        versionName = "0.3.0"
    }

    flavorDimensions += "store"
    productFlavors {
        // What Google Play's policies allow a default-assistant app (docs/clients/android.md).
        create("play") {
            dimension = "store"
        }
        // The Play build without SMS and the call log: no Permissions Declaration to wait for.
        // Same application id as "play": the owner uploads one of the two.
        create("playLite") {
            dimension = "store"
            versionNameSuffix = "-lite"
        }
        // Sideloaded, with everything, including the Accessibility fallback.
        create("personal") {
            dimension = "store"
            applicationIdSuffix = ".personal"
            versionNameSuffix = "-personal"
        }
    }

    signingConfigs {
        if (canSign) {
            create("upload") {
                storeFile = file(uploadStore!!)
                storePassword = uploadStorePassword
                keyAlias = uploadKeyAlias
                keyPassword = uploadKeyPassword
            }
        }
    }

    // Play Lite is the Play build: the same code, its own manifest (src/playLite) drops the permissions.
    sourceSets {
        getByName("playLite") {
            java.directories.add("src/play/java")
            kotlin.directories.add("src/play/java")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            // Symbols of the native code in the bundle (Compose's graphics library), for Play's crash reports.
            ndk { debugSymbolLevel = "SYMBOL_TABLE" }
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            if (canSign) signingConfig = signingConfigs.getByName("upload")
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    implementation(libs.androidx.core)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.process)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.material3)
    implementation(libs.compose.preview)
    debugImplementation(libs.compose.tooling)
    implementation(libs.media3.exoplayer)
    implementation(libs.okhttp)
    implementation(libs.serialization.json)
    implementation(libs.coroutines.android)

    testImplementation(libs.junit)
    testImplementation(libs.coroutines.test)
}
