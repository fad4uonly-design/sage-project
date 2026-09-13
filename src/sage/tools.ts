/**
 * Deterministic tools used when a model should not be trusted to guess.
 *
 * Tool-R0: verify-then-answer gate. A tool result is never released as an
 * answer until it has been verified through an independent evaluation path.
 * `calculate` evaluates via the JS runtime; `evaluateExpression` re-computes
 * with a hand-written recursive-descent parser. Only when both agree does
 * `verifyCalculation` mark the result verified.
 */

const SAFE_EXPRESSION = /^[0-9+\-*/%().\s]+$/;

export function calculate(expression: string): number {
  const trimmed = expression.trim();
  if (!trimmed || !SAFE_EXPRESSION.test(trimmed)) {
    throw new Error("Only arithmetic operators and numbers are allowed.");
  }

  // The allowlist admits only numeric arithmetic syntax; no identifiers,
  // property access, brackets, quotes, or assignment can enter this function.
  const result = Function(`\"use strict\"; return (${trimmed});`)() as unknown;
  if (typeof result !== "number" || !Number.isFinite(result)) {
    throw new Error("The arithmetic result is not finite.");
  }

  return result;
}

// -- Independent evaluation path (recursive-descent parser) -----------------

type Token = { type: "num"; value: number } | { type: "op"; value: string };

function tokenize(expression: string): Token[] {
  const tokens: Token[] = [];
  let index = 0;

  while (index < expression.length) {
    const char = expression[index];

    if (char === " ") {
      index += 1;
      continue;
    }

    if (/[0-9.]/.test(char)) {
      let end = index;
      while (end < expression.length && /[0-9.]/.test(expression[end])) {
        end += 1;
      }
      const value = Number(expression.slice(index, end));
      if (!Number.isFinite(value)) {
        throw new Error(`Invalid number near position ${index}.`);
      }
      tokens.push({ type: "num", value });
      index = end;
      continue;
    }

    if ("+-*/%()".includes(char)) {
      tokens.push({ type: "op", value: char });
      index += 1;
      continue;
    }

    throw new Error(`Unexpected character '${char}' at position ${index}.`);
  }

  return tokens;
}

/**
 * Re-evaluate an arithmetic expression with an explicit parser instead of the
 * JS runtime. Precedence (high → low): unary ± , % , * and / , + and -.
 */
export function evaluateExpression(expression: string): number {
  const tokens = tokenize(expression);
  let position = 0;

  const peek = (): Token | undefined => tokens[position];
  const next = (): Token | undefined => tokens[position++];

  const parsePrimary = (): number => {
    const token = next();
    if (!token) throw new Error("Unexpected end of expression.");

    if (token.type === "num") return token.value;

    if (token.value === "(") {
      const value = parseAdditive();
      const closing = next();
      if (!closing || closing.type !== "op" || closing.value !== ")") {
        throw new Error("Missing closing parenthesis.");
      }
      return value;
    }

    if (token.value === "-") return -parsePrimary();
    if (token.value === "+") return parsePrimary();

    throw new Error(`Unexpected token '${token.value}'.`);
  };

  const parseMultiplicative = (): number => {
    let left = parsePrimary();
    for (;;) {
      const token = peek();
      if (!token || token.type !== "op" || !["*", "/", "%"].includes(token.value)) {
        return left;
      }
      next();
      const right = parsePrimary();
      if (token.value === "*") left = left * right;
      else if (token.value === "/") left = left / right;
      else left = left % right;
    }
  };

  function parseAdditive(): number {
    let left = parseMultiplicative();
    for (;;) {
      const token = peek();
      if (!token || token.type !== "op" || !["+", "-"].includes(token.value)) {
        return left;
      }
      next();
      const right = parseMultiplicative();
      left = token.value === "+" ? left + right : left - right;
    }
  }

  const value = parseAdditive();
  if (position !== tokens.length) {
    throw new Error("Expression was not fully consumed.");
  }
  if (!Number.isFinite(value)) {
    throw new Error("The parsed arithmetic result is not finite.");
  }
  return value;
}

// -- Tool-R0 verify-then-answer gate ----------------------------------------

export interface VerificationResult {
  /** The value SAGE would answer with (only meaningful when verified). */
  value: number;
  /** True only when both independent evaluation paths agree. */
  verified: boolean;
  /** Present when the gate rejects the answer. */
  reason?: string;
}

const RELATIVE_TOLERANCE = 1e-9;

function agrees(left: number, right: number): boolean {
  if (!Number.isFinite(left) || !Number.isFinite(right)) return false;
  const scale = Math.max(1, Math.abs(left), Math.abs(right));
  return Math.abs(left - right) <= RELATIVE_TOLERANCE * scale;
}

/**
 * Tool-R0 gate: compute with the deterministic tool, re-compute with the
 * independent parser, and only release an answer when the two agree.
 */
export function verifyCalculation(expression: string): VerificationResult {
  try {
    const evalValue = calculate(expression);
    try {
      const parsedValue = evaluateExpression(expression);
      if (agrees(evalValue, parsedValue)) {
        return { value: evalValue, verified: true };
      }
      return {
        value: evalValue,
        verified: false,
        reason: `Independent evaluation disagreed (${evalValue} vs ${parsedValue}).`,
      };
    } catch (parserError) {
      return {
        value: evalValue,
        verified: false,
        reason: `Verification parse failed: ${
          parserError instanceof Error ? parserError.message : "unknown"
        }`,
      };
    }
  } catch (toolError) {
    return {
      value: Number.NaN,
      verified: false,
      reason: `Evaluation failed: ${
        toolError instanceof Error ? toolError.message : "unknown"
      }`,
    };
  }
}

