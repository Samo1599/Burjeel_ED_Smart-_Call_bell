plugins { id("com.android.application"); id("org.jetbrains.kotlin.android"); id("com.google.gms.google-services") }
android {
    namespace = "com.burjeel.edcall"
    compileSdk = 35
    buildFeatures { buildConfig = true }
    defaultConfig { applicationId = "com.burjeel.edcall"; minSdk = 26; targetSdk = 35; versionCode = 5; versionName = "0.1.4-pilot"; testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"; buildConfigField("String", "API_ORIGIN", "\"" + providers.gradleProperty("apiOrigin").orElse("https://burjeel-ed-smart-call-bell-dct3.onrender.com").get() + "\"") }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    testOptions { unitTests.isReturnDefaultValues = true }
}
dependencies {
    implementation(platform("com.google.firebase:firebase-bom:34.0.0"))
    implementation("com.google.firebase:firebase-messaging")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("androidx.work:work-runtime-ktx:2.10.1")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:runner:1.6.2")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
}
