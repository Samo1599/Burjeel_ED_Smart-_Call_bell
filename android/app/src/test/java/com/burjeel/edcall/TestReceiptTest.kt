package com.burjeel.edcall
import org.junit.Assert.*
import org.junit.Test
class TestReceiptTest {
 @Test fun acceptsOnlyCurrentFreshTest() {
  assertTrue(TestReceipt.matches("a","a","h","h",1000,2000))
  assertFalse(TestReceipt.matches("a","b","h","h",1000,2000))
  assertFalse(TestReceipt.matches("a","a","h","old",1000,2000))
  assertFalse(TestReceipt.matches("a","a","h","h",1000,62000))
  assertFalse(TestReceipt.matches("a","a","h","h",3000,2000))
  assertFalse(TestReceipt.matches("","","h","h",1000,2000))
 }
}
