// SPDX-License-Identifier: MIT
package org.capybaragram.capture;

public final class CaptureGateTest {
    private static int checks;
    private static void check(boolean value) {
        checks++;
        if (!value) throw new AssertionError("Capture callback boundary " + checks);
    }
    public static void main(String[] args) {
        CaptureGate gate = new CaptureGate();
        check(!gate.claim(null, 1, true));
        CaptureGate.Ticket first = gate.arm();
        check(!gate.claim(first, -1, true));
        check(!gate.claim(first, 0, false));
        check(gate.claim(first, 0, true));
        check(!gate.claim(first, 0, true));
        check(!gate.claim(first, 1999, true));
        check(gate.claim(first, 2000, true));
        check(!gate.claim(first, 1000, true));
        check(!gate.claim(first, 4000, false));
        check(gate.claim(first, 4000, true));
        gate.revoke();
        check(!gate.claim(first, 6000, true));
        CaptureGate.Ticket second = gate.arm();
        check(!gate.claim(first, 6000, true));
        check(gate.claim(second, 6000, true));
        check(!gate.claim(second, 7999, true));
        check(gate.claim(second, 8000, true));
        CaptureGate other = new CaptureGate();
        CaptureGate.Ticket foreign = other.arm();
        check(!gate.claim(foreign, 10000, true));
        check(!other.claim(second, 10000, true));
        check(other.claim(foreign, 10000, true));
        CaptureGate.Ticket latest = gate.arm();
        check(!gate.claim(second, 12000, true));
        check(gate.claim(latest, 12000, true));
        gate.revoke();
        gate.revoke();
        check(!gate.claim(latest, Long.MAX_VALUE, true));
        System.out.println("CAPY_CAPTURE_GATE=PASS checks=" + checks);
    }
}
