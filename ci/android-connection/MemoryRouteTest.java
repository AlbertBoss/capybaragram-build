// SPDX-License-Identifier: MIT
package org.capybaragram.connection;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public final class MemoryRouteTest {
    private static int assertions;
    private static void check(boolean value,String label) { assertions++;if (!value) throw new AssertionError(label); }
    private static byte[] token() {
        byte[] bytes=new byte[36];bytes[0]=12;bytes[1]=4;bytes[2]='d';bytes[3]='d';
        Arrays.fill(bytes,4,36,(byte)'b');return bytes;
    }
    private static final class Applied {
        final int account,port;final boolean enabled;final String address,username,password,secret;
        Applied(int account,boolean enabled,String address,int port,String username,String password,String secret) {
            this.account=account;this.enabled=enabled;this.address=address;this.port=port;
            this.username=username;this.password=password;this.secret=secret;
        }
    }
    public static void main(String[] arguments) throws Exception {
        List<Applied> calls=new ArrayList<>();
        MemoryRoute route=new MemoryRoute(10,(a,e,h,p,u,w,s)->calls.add(new Applied(a,e,h,p,u,w,s)));
        MemoryRoute.Proxy saved=new MemoryRoute.Proxy(true,"manual.example.invalid",1443,"test-user","test-pass","test-secret");
        route.beforeInitialize(0,saved);route.afterInitialize(0);
        check(calls.size()==2 && calls.get(1).address.equals(saved.address),"native initialization keeps saved proxy");
        long enabled=route.begin(true,saved);
        check(calls.size()==3 && route.snapshot().phase==MemoryRoute.Phase.STARTING,"only initialized account updated while starting");
        byte[] endpoint=token();check(route.ready(enabled,endpoint),"current route accepted");
        Arrays.fill(endpoint,(byte)0);
        Applied first=calls.get(calls.size()-1);
        check(first.account==0 && first.enabled && first.address.equals("127.0.0.1") && first.port==1036,"local MTProto endpoint applied");
        check(first.secret.equals("ddbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb") && first.username.isEmpty() && first.password.isEmpty(),"token owned independently of caller buffer");
        int before=calls.size();
        route.beforeInitialize(9,saved);
        long manual=route.manualSelected(new MemoryRoute.Proxy(false,"",0,null,null,null));
        route.afterInitialize(9);
        check(calls.size()==before+3,"new slot tracked only after native initialization");
        check(!calls.get(calls.size()-1).enabled,"manual selection during native_init wins after initialization");
        check(!route.ready(enabled,token()) && !route.failed(enabled),"revoked completion cannot change manual settings");
        check(route.snapshot().generation==manual && !route.snapshot().requested,"manual generation immediately revoked activation");
        enabled=route.begin(true,saved);before=calls.size();
        check(!route.ready(enabled,null) && !route.ready(enabled,new byte[35]) && !route.ready(enabled,new byte[37]),"invalid JNI endpoint lengths refused");
        byte[] invalid=token();invalid[0]=invalid[1]=0;
        check(!route.ready(enabled,invalid),"zero port refused");
        invalid=token();invalid[4]='z';check(!route.ready(enabled,invalid),"invalid hexadecimal token refused");
        check(calls.size()==before,"invalid endpoint never reaches native setter");
        check(route.ready(enabled,token()),"retry accepts valid endpoint");
        check(calls.size()==before+2 && calls.get(before).account==0 && calls.get(before+1).account==9,"ten slots supported without initializing eight unused accounts");
        check(route.failed(enabled),"current failure restores normal route");
        check(route.snapshot().phase==MemoryRoute.Phase.FAILED && !calls.get(calls.size()-1).enabled,"failure restores latest disabled manual route");
        long newer=route.begin(true,saved);check(!route.ready(enabled,token()),"older activation cannot overwrite newer activation");
        check(route.ready(newer,token()),"newest activation accepted");
        long disabled=route.begin(false,saved);
        check(!route.ready(newer,token()) && route.snapshot().generation==disabled,"disable revokes queued readiness");
        route.manualSelected(saved);before=calls.size();
        long last=route.begin(true,saved);check(route.ready(last,token()),"configured manual proxy can be temporarily overridden");
        route.begin(false,saved);
        Applied restored=calls.get(calls.size()-1);
        check(restored.address.equals(saved.address) && restored.port==saved.port && restored.username.equals(saved.username)
                && restored.password.equals(saved.password) && restored.secret.equals(saved.secret),"all original proxy fields restored without preference writes");
        check(calls.size()==before+6,"three route changes target two initialized slots only");
        boolean invalidSlot=false;
        try { route.beforeInitialize(10,saved); } catch(IllegalArgumentException expected) { invalidSlot=true; }
        check(invalidSlot,"out-of-range account refused");
        System.out.println("CAPY_ANDROID_MEMORY_ROUTE=PASS "+assertions+" assertions");
    }
}
