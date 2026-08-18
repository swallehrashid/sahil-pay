import { useRef } from "react";

// 6-box OTP entry used by TenantOtpLogin (and any future 2FA flow).
export default function OtpInput({ length = 6, value = "", onChange }) {
  const inputsRef = useRef([]);
  const digits = value.split("").concat(Array(length).fill("")).slice(0, length);

  const setDigit = (index, digit) => {
    const next = [...digits];
    next[index] = digit;
    onChange?.(next.join(""));
  };

  const handleChange = (index, e) => {
    const digit = e.target.value.replace(/\D/g, "").slice(-1);
    setDigit(index, digit);
    if (digit && index < length - 1) inputsRef.current[index + 1]?.focus();
  };

  const handleKeyDown = (index, e) => {
    if (e.key === "Backspace" && !digits[index] && index > 0) {
      inputsRef.current[index - 1]?.focus();
    }
  };

  const handlePaste = (e) => {
    const pasted = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, length);
    if (!pasted) return;
    e.preventDefault();
    onChange?.(pasted.padEnd(length, ""));
    inputsRef.current[Math.min(pasted.length, length - 1)]?.focus();
  };

  return (
    <div className="flex justify-center gap-2" onPaste={handlePaste}>
      {digits.map((digit, index) => (
        <input
          key={index}
          ref={(el) => (inputsRef.current[index] = el)}
          value={digit}
          onChange={(e) => handleChange(index, e)}
          onKeyDown={(e) => handleKeyDown(index, e)}
          inputMode="numeric"
          // one-time-code lets iOS and Android offer the code straight from the
          // SMS notification. A tenant reading six digits off a lock screen and
          // retyping them is the step where people give up on OTP sign-in.
          // Only the first box carries it — repeating it on all six makes the
          // suggestion fire per box.
          autoComplete={index === 0 ? "one-time-code" : "off"}
          name={index === 0 ? "code" : undefined}
          aria-label={`Digit ${index + 1} of ${length}`}
          maxLength={1}
          className="glass-input h-12 w-11 text-center text-lg font-medium"
        />
      ))}
    </div>
  );
}
