package com.burjeel.edcall

interface CredentialStateStorage {
    var credential: String
    var previousCredential: String
    var pendingCredential: String
    var token: String
    var revision: Long
}
data class DeviceSnapshot(val revision: Long,val credential: String,val token: String)

class DeviceLifecycle(private val state: CredentialStateStorage) {
    companion object { private val lock=Any() }
    fun snapshot(): DeviceSnapshot = synchronized(lock) { DeviceSnapshot(state.revision,state.credential,state.token) }
    fun isCurrent(snapshot: DeviceSnapshot): Boolean = synchronized(lock) { state.revision==snapshot.revision && state.credential==snapshot.credential }
    fun acceptEnrollment(attempt: DeviceSnapshot,credential: String): Boolean = synchronized(lock) {
        if(!isCurrent(attempt) || state.pendingCredential.isNotEmpty()) {
            state.pendingCredential=credential
            false
        } else {
            state.credential=credential;state.previousCredential="";state.revision++
            true
        }
    }
    fun beginLogout() = synchronized(lock) {
        state.revision++
        if(state.credential.isNotEmpty()) state.pendingCredential=state.credential
        state.credential=""
    }
    fun rejectCredential(credential: String) = synchronized(lock) {
        if(state.credential==credential) { state.credential="";state.revision++ }
    }
    fun rotateToken(token: String) = synchronized(lock) { state.token=token }
    fun finishRevocation(credential: String): Boolean = synchronized(lock) {
        if(state.pendingCredential!=credential) false else {
            state.previousCredential=credential;state.pendingCredential="";state.revision++;true
        }
    }
}
