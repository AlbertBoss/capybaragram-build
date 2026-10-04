// SPDX-License-Identifier: MIT
package org.capybaragram.connection;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.BooleanSupplier;

public final class ConnectionControllerTest {
    private static int assertions;
    private static void check(boolean value,String label) { assertions++;if (!value) throw new AssertionError(label); }
    private static void waitFor(BooleanSupplier condition,String label) throws InterruptedException {
        long until=System.nanoTime()+TimeUnit.SECONDS.toNanos(4);
        while (!condition.getAsBoolean() && System.nanoTime()<until) Thread.sleep(2);
        check(condition.getAsBoolean(),label);
    }
    private static final class Ui implements ConnectionController.Dispatcher {
        final ArrayDeque<Runnable> queue=new ArrayDeque<>();int maximum;
        @Override public synchronized void post(Runnable runnable) { queue.add(runnable);maximum=Math.max(maximum,queue.size()); }
        synchronized int size() { return queue.size(); }
        void drain() { while (true) { Runnable next;synchronized(this) { next=queue.poll(); }if(next==null)return;next.run(); } }
    }
    private static final class Native implements ConnectionController.Engine {
        final AtomicInteger starts=new AtomicInteger(),stops=new AtomicInteger();
        final CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);
        volatile boolean block,invalid;
        volatile byte[] latest;
        volatile String nativeThread;
        @Override public long start(byte[] endpoint) {
            nativeThread=Thread.currentThread().getName();int number=starts.incrementAndGet();
            entered.countDown();
            if (block) {
                try { if(!release.await(4,TimeUnit.SECONDS))throw new AssertionError("test gate deadline"); }
                catch (InterruptedException error) { throw new AssertionError(error); }
            }
            endpoint[0]=11;endpoint[1]=3;endpoint[2]='d';endpoint[3]='d';Arrays.fill(endpoint,4,36,(byte)'a');
            latest=endpoint;return number;
        }
        @Override public boolean status(long handle,int[] status) { status[0]=1;status[1]=invalid?0:1;return true; }
        @Override public int stop(long handle) { stops.incrementAndGet();return 1; }
    }
    public static void main(String[] arguments) throws Exception {
        // Disable while native start is blocked; no stale READY is delivered.
        Native nativeEngine=new Native();nativeEngine.block=true;Ui ui=new Ui();List<ConnectionController.Phase> phases=new ArrayList<>();
        ConnectionController controller=new ConnectionController(nativeEngine,ui,u->phases.add(u.phase));
        controller.setEnabled(true);check(nativeEngine.entered.await(4,TimeUnit.SECONDS),"worker reached start");
        long began=System.nanoTime();long disabled=controller.setEnabled(false);
        check(System.nanoTime()-began<TimeUnit.MILLISECONDS.toNanos(100),"disable does not wait for native start");
        nativeEngine.release.countDown();waitFor(()->ui.size()==1,"disabled delivery scheduled");ui.drain();
        check(phases.equals(Arrays.asList(ConnectionController.Phase.DISABLED)),"blocked start cannot restore disabled route");
        check(nativeEngine.starts.get()==1 && nativeEngine.stops.get()==1,"stale native instance stopped");
        check(Arrays.equals(nativeEngine.latest,new byte[36]),"stale endpoint wiped");
        check(!nativeEngine.nativeThread.equals(Thread.currentThread().getName()),"start runs off caller thread");
        check(disabled>0,"monotonic command revision");controller.close();waitFor(controller::isTerminated,"disabled worker terminates");

        // A queued READY must be revoked and wiped before it can reach a closed UI.
        Native queued=new Native();Ui queuedUi=new Ui();List<ConnectionController.Phase> delivered=new ArrayList<>();
        ConnectionController closed=new ConnectionController(queued,queuedUi,u->delivered.add(u.phase));
        closed.setEnabled(true);waitFor(()->queuedUi.size()==1,"ready delivery queued");
        check(queued.latest[2]=='d',"callback endpoint present while queued");
        began=System.nanoTime();closed.close();
        check(System.nanoTime()-began<TimeUnit.MILLISECONDS.toNanos(100),"close does not join native worker");
        check(Arrays.equals(queued.latest,new byte[36]),"close wipes queued token immediately");queuedUi.drain();
        check(delivered.isEmpty(),"destroyed owner receives no ready callback");
        waitFor(closed::isTerminated,"closed worker terminates");check(queued.stops.get()==1,"owned listener stopped on close");
        check(closed.setEnabled(true)==-1,"closed controller refuses new work");

        // Rapid requests replace pending work and one UI callback, not thread creation.
        Native burst=new Native();burst.block=true;Ui burstUi=new Ui();List<ConnectionController.Phase> burstPhases=new ArrayList<>();
        ConnectionController rapid=new ConnectionController(burst,burstUi,u->burstPhases.add(u.phase));
        rapid.setEnabled(true);check(burst.entered.await(4,TimeUnit.SECONDS),"burst start blocked");
        for(int i=0;i<2000;i++)rapid.setEnabled((i&1)==0);
        burst.release.countDown();waitFor(()->burstUi.size()==1,"latest burst command delivered");burstUi.drain();
        check(burstPhases.equals(Arrays.asList(ConnectionController.Phase.DISABLED)),"latest request wins");
        check(burst.starts.get()==1 && burst.stops.get()==1,"superseded starts never execute");
        check(burstUi.maximum==1,"only one UI delivery queued");rapid.close();waitFor(rapid::isTerminated,"burst worker terminates");

        Native bad=new Native();bad.invalid=true;Ui badUi=new Ui();List<ConnectionController.Phase> badPhases=new ArrayList<>();
        ConnectionController rejected=new ConnectionController(bad,badUi,u->badPhases.add(u.phase));
        rejected.setEnabled(true);waitFor(()->badUi.size()==1,"invalid readiness delivered");badUi.drain();
        check(badPhases.equals(Arrays.asList(ConnectionController.Phase.FAILED)),"running false is never ready");
        check(bad.stops.get()==1 && Arrays.equals(bad.latest,new byte[36]),"failed endpoint closed and wiped");
        rejected.close();waitFor(rejected::isTerminated,"failed worker terminates");
        System.out.println("CAPY_ANDROID_CONNECTION_CONTROLLER=PASS "+assertions+" assertions; 2000 requests coalesced");
    }
}
