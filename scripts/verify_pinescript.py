"""
Verification script for Pine Script files
"""
import sys

def verify_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    brackets = {'(': ')', '[': ']', '{': '}'}
    stack = []
    
    for line_idx, line in enumerate(lines, 1):
        clean = line.split('//')[0]
        in_str = False
        quote_char = ''
        
        for col_idx, ch in enumerate(clean, 1):
            if ch in ('"', "'"):
                if in_str and ch == quote_char:
                    in_str = False
                elif not in_str:
                    in_str = True
                    quote_char = ch
            elif not in_str:
                if ch in '([{':
                    stack.append((ch, line_idx, col_idx))
                elif ch in ')]}':
                    if not stack:
                        print(f"Error in {filepath}: unexpected '{ch}' at line {line_idx}:{col_idx}")
                        return False
                    top, top_l, top_c = stack.pop()
                    if brackets[top] != ch:
                        print(f"Mismatch in {filepath}: '{top}' at line {top_l}:{top_c} closed by '{ch}' at line {line_idx}:{col_idx}")
                        return False
                        
    if stack:
        print(f"Unclosed brackets in {filepath}: {stack[:5]}")
        return False
        
    print(f"SUCCESS: {filepath} ({len(lines)} lines) passed all bracket checks!")
    return True

if __name__ == '__main__':
    ok1 = verify_file('tradingview/quantum_microstructure_swing_indicator.pine')
    ok2 = verify_file('tradingview/quantum_microstructure_swing_strategy.pine')
    if ok1 and ok2:
        print("ALL PINE SCRIPTS VERIFIED SUCCESSFULLY!")
    else:
        sys.exit(1)
