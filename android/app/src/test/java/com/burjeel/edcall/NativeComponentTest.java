package com.burjeel.edcall;
import org.junit.Test;
import static org.junit.Assert.*;
public class NativeComponentTest {
 @Test public void nativeReceiverExistsIndependentlyOfWebView() {
  Class<?> receiver=null;
  try { receiver=Class.forName("com.burjeel.edcall.CallMessagingService"); } catch(ClassNotFoundException ignored) {}
  assertNotNull("Native FCM receiver must exist",receiver);
 }
}
