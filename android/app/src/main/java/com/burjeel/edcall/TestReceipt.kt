package com.burjeel.edcall

/** A fresh, matching receipt belongs to this enrollment and this test only. */
object TestReceipt {
    fun matches(expectedEvent: String, event: String, expectedRegistration: String, registration: String, receivedAt: Long, now: Long): Boolean =
        expectedEvent.isNotEmpty() && expectedEvent==event && expectedRegistration.isNotEmpty() && expectedRegistration==registration && now>=receivedAt && now-receivedAt<=60000
}
