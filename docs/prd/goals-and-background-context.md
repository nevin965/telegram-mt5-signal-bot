# Goals and Background Context

## Goals
• Achieve 100% automated execution of French GOLD trading signals from Telegram groups within 2 seconds
• Enable 24/5 unattended trading operation across all market sessions without manual intervention  
• Implement intelligent context-aware signal correlation for updates like "BREAK EVEN" and "CLÔTUREZ"
• Automate stop-loss adjustments to entry +1 pip for proper risk management and prop firm compliance
• Maintain accurate position tracking through SQLite database that persists across system restarts
• Process text-based signals using gpt-5-mini for French language understanding and context interpretation
• Ensure zero missed signals due to system failures with automatic recovery mechanisms
• Keep operational costs under €50/month while maintaining reliable API service usage

## Background Context

This PRD addresses the critical execution gap faced by traders following French-language Telegram signal groups, where manual monitoring causes 30-60 second delays resulting in 5-20 pip slippage on volatile GOLD trades. The system leverages a hybrid approach combining regex pattern matching for standard signals and gpt-5-mini for contextual interpretation of French trading terminology and reply patterns. Unlike existing solutions like TSCopier that fail with French signals and contextual updates, this EA treats signal groups as conversations, maintaining message correlation to correctly match updates like "BREAK EVEN +30" to their parent positions even with multiple open trades.

## Change Log

| Date | Version | Description | Author |
|------|---------|-------------|---------|
| 2024-12-11 | 1.0 | Initial PRD creation based on Project Brief | John (PM) |
