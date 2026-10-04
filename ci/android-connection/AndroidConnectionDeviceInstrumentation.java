// SPDX-License-Identifier: MIT
package org.capybaragram.connection;

import android.app.Activity;
import android.app.Instrumentation;
import android.os.Bundle;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketException;
import java.util.Arrays;

/** Actual JNI and loopback execution; no Telegram login or outbound test traffic. */
public final class AndroidConnectionDeviceInstrumentation extends Instrumentation {
    private int assertions;
    private void check(boolean value, String label) {
        assertions++;
        if (!value) throw new AssertionError(label);
    }
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments); start(); }
    private int endpoint(byte[] bytes) {
        int port=(bytes[0]&255)|((bytes[1]&255)<<8);
        check(port>0, "ephemeral port");
        check(bytes[2]=='d' && bytes[3]=='d', "padded MTProto secret");
        for (int i=4;i<36;i++) {
            int value=bytes[i]&255;
            check((value>='0' && value<='9') || (value>='a' && value<='f'), "hex secret");
        }
        return port;
    }
    private void running(long handle) {
        int[] status=new int[7];
        check(NativeTunnel.status(handle,status), "handle live");
        check(status[0]==1 && status[1]==1, "ABI and listener ready");
        check(status[2]>=0 && status[2]<=128, "bounded client count");
        check(status[3]==0 && status[4]==0 && status[5]==0 && status[6]==0,
                "listener readiness does not invent established Telegram tunnel");
    }
    @Override public void onStart() {
        Bundle result=new Bundle();
        long first=0, second=0;
        byte[] firstEndpoint=new byte[36], secondEndpoint=new byte[36];
        try {
            check(NativeTunnel.start(null)==0, "null endpoint refused");
            check(NativeTunnel.start(new byte[35])==0, "short endpoint refused");
            check(NativeTunnel.start(new byte[37])==0, "oversized endpoint refused");
            check(!NativeTunnel.status(0,new int[7]), "zero handle refused");
            check(!NativeTunnel.status(-1,new int[7]), "negative handle refused");
            check(!NativeTunnel.status(1,null), "null status refused");
            check(!NativeTunnel.status(1,new int[6]), "short status refused");
            check(!NativeTunnel.status(1,new int[8]), "oversized status refused");
            check(NativeTunnel.stop(0)==0 && NativeTunnel.stop(-1)==0, "invalid stop is harmless");
            first=NativeTunnel.start(firstEndpoint);check(first>0, "first listener created");
            second=NativeTunnel.start(secondEndpoint);check(second>0 && second!=first, "independent opaque handle");
            int firstPort=endpoint(firstEndpoint), secondPort=endpoint(secondEndpoint);
            check(firstPort!=secondPort, "independent listener ports");
            check(!Arrays.equals(firstEndpoint,secondEndpoint), "independent endpoint bytes");
            // Do not retain the random tokens while testing unrelated boundaries.
            Arrays.fill(firstEndpoint,(byte)0);Arrays.fill(secondEndpoint,(byte)0);
            running(first);running(second);
            try (Socket socket=new Socket()) {
                socket.connect(new InetSocketAddress("127.0.0.1",firstPort),2000);
                socket.setSoTimeout(5000);
                socket.getOutputStream().write(new byte[]{5,1,0});socket.getOutputStream().flush();
                boolean refused;
                try { refused=socket.getInputStream().read()==-1; }
                catch (SocketException reset) { refused=true; }
                check(refused, "embedded listener refuses SOCKS before outbound dial");
            }
            long revoked=first;
            check(NativeTunnel.stop(first)==1, "first stopped");first=0;
            check(NativeTunnel.stop(revoked)==0, "stop idempotent");
            int[] cleared=new int[7];Arrays.fill(cleared,-1);
            check(!NativeTunnel.status(revoked,cleared), "revoked handle refused");
            check(Arrays.equals(cleared,new int[7]), "failed status cannot reuse stale ready state");
            running(second);
            check(NativeTunnel.stop(second)==1, "second stopped independently");second=0;
            long previous=revoked;
            for (int i=0;i<8;i++) {
                long handle=NativeTunnel.start(firstEndpoint);
                check(handle>previous, "handle never reused");first=handle;
                endpoint(firstEndpoint);Arrays.fill(firstEndpoint,(byte)0);
                running(handle);
                check(NativeTunnel.stop(handle)==1, "repeated start stop");first=0;
                check(!NativeTunnel.status(handle,new int[7]), "repeated handle revoked");
                previous=handle;
            }
            result.putString("stream","CAPY_ANDROID_CONNECTION_JNI=PASS "+assertions+" assertions\n");
            finish(Activity.RESULT_OK,result);
        } catch (Throwable error) {
            // Test-only labels; no endpoint, Telegram session or key is printed.
            result.putString("stream","CAPY_ANDROID_CONNECTION_JNI=FAIL "+error.getClass().getSimpleName()+": "+error.getMessage()+"\n");
            finish(Activity.RESULT_CANCELED,result);
        } finally {
            Arrays.fill(firstEndpoint,(byte)0);Arrays.fill(secondEndpoint,(byte)0);
            if (first>0) NativeTunnel.stop(first);
            if (second>0) NativeTunnel.stop(second);
        }
    }
}
