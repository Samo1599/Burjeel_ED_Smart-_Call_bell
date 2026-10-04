package com.burjeel.edcall
import android.content.Context
import androidx.work.*
import java.util.concurrent.TimeUnit

class TokenRefreshWorker(context: Context, params: WorkerParameters): Worker(context,params) {
    override fun doWork(): Result {
        val store=DeviceStore(applicationContext); val client=EnrollmentClient(store)
        val snapshot=store.lifecycle.snapshot()
        val pending=store.pendingCredential
        return try {
            if(pending.isNotEmpty()) { client.revoke(pending); store.lifecycle.finishRevocation(pending) }
            if(snapshot.credential.isNotEmpty() && snapshot.token.isNotEmpty()) client.refresh(snapshot.token,snapshot.credential)
            Result.success()
        } catch(e: ApiFailure) {
            if(e.status==401) {
                if(pending.isNotEmpty()) store.lifecycle.finishRevocation(pending)
                store.lifecycle.rejectCredential(snapshot.credential)
                Result.success()
            } else if(NativePolicy.shouldRetry(e.status)) Result.retry() else Result.failure()
        } catch (_: Exception) { Result.retry() }
    }

    companion object {
        fun schedule(context: Context) {
            val request=OneTimeWorkRequestBuilder<TokenRefreshWorker>().setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS).build()
            WorkManager.getInstance(context).enqueueUniqueWork("native-token-refresh",ExistingWorkPolicy.APPEND_OR_REPLACE,request)
        }
    }
}
