#!/usr/bin/env python3
"""
Pre-commit hook script for checking code similarity using similarity-py.

This script runs similarity-py to detect code duplications that may benefit from refactoring.
It's designed as a warning system rather than a blocking check, since high similarity
might be acceptable in certain structural contexts.
"""

import subprocess
import sys
from pathlib import Path


def run_similarity_check() -> int:
    """
    Run similarity-py with configured parameters and format the output.
    
    Returns:
        0: No high similarity found or acceptable similarities
        1: High similarity found that should be reviewed
    """
    # Get the project root directory
    project_root = Path(__file__).parent.parent
    
    # Configuration
    threshold = 0.85
    min_lines = 10
    
    try:
        # Run similarity-py with specified parameters
        cmd = [
            "similarity-py",
            "--threshold", str(threshold),
            "--min-lines", str(min_lines),
            "--print",  # Print code in output for review
            str(project_root / "rd_burndown")  # Target directory
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=project_root
        )
        
        if result.returncode != 0:
            print(f"❌ Error running similarity-py: {result.stderr}")
            return 1
        
        output = result.stdout.strip()
        
        if not output or "No similar functions found" in output:
            print("✅ No high code similarity detected (threshold: 85%, min lines: 10)")
            return 0
        
        # High similarity found - format the warning
        print("⚠️  CODE SIMILARITY WARNING")
        print("=" * 50)
        print(f"Detected code with ≥{threshold*100:.0f}% similarity (minimum {min_lines} lines):")
        print()
        print(output)
        print()
        print("📋 REVIEW GUIDELINES:")
        print("- High similarity may indicate potential for refactoring")
        print("- However, similarity might be acceptable if:")
        print("  • Code follows necessary structural patterns")
        print("  • Refactoring would reduce readability")
        print("  • Functions serve different business contexts")
        print("  • Similar code is in different modules/layers")
        print("  • The duplication is intentional for performance/clarity")
        print()
        print("💡 Consider extracting common logic into:")
        print("  • Shared utility functions")
        print("  • Base classes or mixins")
        print("  • Configuration-driven approaches")
        print("  • Template methods or strategy patterns")
        print()
        print("⚡ This is a WARNING, not a blocking error.")
        print("   You can proceed with the commit if refactoring isn't appropriate.")
        
        # Return 0 (success) to make this a warning rather than blocking the commit
        return 0
        
    except FileNotFoundError:
        print("❌ similarity-py not found. Please ensure it's installed:")
        print("   cargo install similarity-py")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(run_similarity_check())