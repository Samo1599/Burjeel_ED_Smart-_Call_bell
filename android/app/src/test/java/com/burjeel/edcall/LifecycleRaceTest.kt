package com.burjeel.edcall
import org.junit.Assert.*
import org.junit.Test

class MemoryState: CredentialStateStorage {
    override var credential=""
    override var previousCredential=""
    override var pendingCredential=""
    override var token=""
    override var revision=0L
}
class LifecycleRaceTest {
    @Test fun logoutInvalidatesInflightEnrollmentAndQueuesOrphanRevoke() {
        val state=MemoryState(); val lifecycle=DeviceLifecycle(state)
        val attempt=lifecycle.snapshot()
        lifecycle.beginLogout()
        assertFalse(lifecycle.acceptEnrollment(attempt,"late-credential"))
        assertEquals("",state.credential)
        assertEquals("late-credential",state.pendingCredential)
        assertFalse(lifecycle.isCurrent(attempt))
    }
    @Test fun staleRefreshCannotClearNewCredential() {
        val state=MemoryState();val lifecycle=DeviceLifecycle(state)
        assertTrue(lifecycle.acceptEnrollment(lifecycle.snapshot(),"A"))
        val old=lifecycle.snapshot()
        assertTrue(lifecycle.acceptEnrollment(lifecycle.snapshot(),"B"))
        lifecycle.rejectCredential(old.credential)
        assertEquals("B",state.credential)
    }
    @Test fun rotationDuringEnrollmentPreservesLatestToken() {
        val state=MemoryState();val lifecycle=DeviceLifecycle(state)
        lifecycle.rotateToken("A");val attempt=lifecycle.snapshot()
        lifecycle.rotateToken("B")
        assertTrue(lifecycle.acceptEnrollment(attempt,"credential"))
        assertEquals("B",state.token)
    }
    @Test fun oldRevocationCompletionCannotClearNewPendingCredential() {
        val state=MemoryState();val lifecycle=DeviceLifecycle(state)
        state.pendingCredential="new-pending"
        assertFalse(lifecycle.finishRevocation("old-pending"))
        assertEquals("new-pending",state.pendingCredential)
    }
}
