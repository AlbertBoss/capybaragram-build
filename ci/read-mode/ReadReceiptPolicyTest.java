// SPDX-License-Identifier: MIT
package org.capybaragram.readmode;

public final class ReadReceiptPolicyTest {
    private static int checks;
    private static void check(boolean value, String label) {
        checks++;
        if (!value) throw new AssertionError(label);
    }
    public static void main(String[] args) throws Exception {
        ReadReceiptPolicy[] accounts = new ReadReceiptPolicy[10];
        for (int i=0;i<accounts.length;i++) accounts[i]=new ReadReceiptPolicy(true);
        ReadReceiptPolicy a=accounts[0], b=accounts[1];
        ReadReceiptPolicy.Ticket explicitA=a.capture(true);
        check(!b.consume(explicitA), "another account must not use or consume A's permit");
        check(!b.consume(b.capture(false)), "B automatic receipt stays suppressed");
        check(a.consume(explicitA), "A's explicit request remains allowed");
        check(!a.consume(explicitA), "permit cannot be replayed");
        for (int i=0;i<accounts.length;i++) {
            check(!accounts[i].consume(accounts[i].capture(false)), "silent account "+i);
        }

        ReadReceiptPolicy.Ticket readWhileSilent=a.capture(false);
        a.setSilent(false);
        check(!a.consume(readWhileSilent), "turning mode off must not flush a suppressed request");
        check(a.consume(a.capture(false)), "new normal request after disabling mode");
        ReadReceiptPolicy.Ticket queuedNormal=a.capture(false);
        a.setSilent(true);
        check(!a.consume(queuedNormal), "enabling mode suppresses a still queued request");

        ReadReceiptPolicy.Ticket oldSession=a.capture(true);
        a.reset(true);
        check(!a.consume(oldSession), "logout/relogin invalidates explicit request");
        check(a.consume(a.capture(true)), "new session explicit request allowed");
        check(!a.consume(null), "missing ticket fails closed");

        ReadReceiptPolicy.Ticket once=a.capture(true);
        java.util.concurrent.atomic.AtomicInteger sent=new java.util.concurrent.atomic.AtomicInteger();
        Thread t1=new Thread(()->{if(a.consume(once))sent.incrementAndGet();});
        Thread t2=new Thread(()->{if(a.consume(once))sent.incrementAndGet();});
        t1.start();t2.start();t1.join();t2.join();
        check(sent.get()==1,"concurrent consumers may send only once");
        System.out.println("CAPY_READ_POLICY=PASS checks="+checks);
    }
}
