package com.burjeel.edcall
import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class DeviceStore(context: Context): CredentialStateStorage {
    private val preferences=context.getSharedPreferences("native_device",Context.MODE_PRIVATE)
    val installationId: String get() {
        var id=preferences.getString("installation",null)
        if (id==null) { id=UUID.randomUUID().toString(); preferences.edit().putString("installation",id).commit() }
        return id
    }
    private fun key(): SecretKey {
        val store=KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val alias="burjeel_native_device"
        (store.getKey(alias,null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }
    private fun read(name: String): String {
        val stored=preferences.getString(name,null) ?: return ""
        return try {
            val bytes=Base64.decode(stored,Base64.NO_WRAP)
            val cipher=Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE,key(),GCMParameterSpec(128,bytes.copyOfRange(0,12)))
            String(cipher.doFinal(bytes.copyOfRange(12,bytes.size)))
        } catch (_: Exception) { "" }
    }
    private fun write(name: String,value: String) {
        if (value.isEmpty()) { preferences.edit().remove(name).commit(); return }
        val cipher=Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE,key())
        preferences.edit().putString(name,Base64.encodeToString(cipher.iv+cipher.doFinal(value.toByteArray()),Base64.NO_WRAP)).commit()
    }
    override var credential: String get()=read("credential"); set(value)=write("credential",value)
    override var previousCredential: String get()=read("previous"); set(value)=write("previous",value)
    override var token: String get()=read("fcm_token"); set(value)=write("fcm_token",value)
    override var pendingCredential: String get()=read("pending"); set(value)=write("pending",value)
    override var revision: Long get()=preferences.getLong("revision",0L); set(value) { preferences.edit().putLong("revision",value).commit() }
    val lifecycle=DeviceLifecycle(this)
    val pendingRevocation: Boolean get()=pendingCredential.isNotEmpty()
    val registered: Boolean get()=credential.isNotEmpty() && !pendingRevocation
    var testReceipt: String get()=read("test_receipt"); set(value)=write("test_receipt",value)
    fun beginRevocation() { lifecycle.beginLogout() }
    fun finishRevocation() { lifecycle.finishRevocation(pendingCredential) }
}
