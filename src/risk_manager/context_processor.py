"""Context processor for handling LLM analysis results with confidence-based execution."""

from datetime import datetime
from enum import Enum
from typing import Any

from config.logging_config import (
    get_contextual_logger,
    set_correlation_id,
    set_service_context,
)
from src.database.models import Position, PositionUpdate, UpdateType
from src.database.repository import RepositoryFactory
from src.signal_parser.context_analyzer import ContextAnalysisResult, TelegramMessage


class ExecutionResult(Enum):
    """Result of context processing execution."""
    EXECUTED = "EXECUTED"
    QUEUED_FOR_REVIEW = "QUEUED_FOR_REVIEW"
    FAILED = "FAILED"
    INVALID_ACTION = "INVALID_ACTION"


class ContextProcessor:
    """
    Processes LLM context analysis results and routes to appropriate processors.
    
    Implements confidence-based execution with automatic routing for high-confidence
    updates and manual review queuing for low-confidence results.
    """

    # Confidence threshold for automatic execution (AC: 4)
    CONFIDENCE_THRESHOLD = 0.75

    def __init__(self, repository_factory: RepositoryFactory) -> None:
        """Initialize context processor with repository for database operations."""
        self.logger = get_contextual_logger(__name__)
        self.repository_factory = repository_factory

    async def process_context_analysis(
        self,
        analysis_result: ContextAnalysisResult,
        message: TelegramMessage,
        positions: list[Position]
    ) -> tuple[ExecutionResult, dict[str, Any] | None]:
        """
        Process LLM context analysis result and execute or queue for review.
        
        Args:
            analysis_result: Result from ContextAnalyzer
            message: Original update message
            positions: List of open positions
            
        Returns:
            Tuple of (ExecutionResult, execution_details)
        """
        if not analysis_result:
            return ExecutionResult.FAILED, {"error": "No analysis result provided"}

        # Set service context for logging
        set_service_context("ContextProcessor", "process_context_analysis")
        correlation_id = analysis_result.correlation_id or set_correlation_id()

        # Log processing start
        self.logger.info(
            "Context analysis processing started",
            extra_fields={
                "context_processing": {
                    "action": analysis_result.action,
                    "confidence": analysis_result.confidence,
                    "target_position": analysis_result.target_position,
                    "correlation_id": correlation_id,
                    "above_threshold": analysis_result.confidence >= self.CONFIDENCE_THRESHOLD
                }
            }
        )

        try:
            # Validate analysis result
            validation_result = self._validate_analysis_result(analysis_result, positions)
            if not validation_result["is_valid"]:
                await self._log_validation_failure(analysis_result, message, validation_result["errors"])
                return ExecutionResult.INVALID_ACTION, validation_result

            # Check confidence threshold (AC: 4, 5)
            if analysis_result.confidence >= self.CONFIDENCE_THRESHOLD:
                # High confidence - attempt automatic execution
                execution_result = await self._execute_high_confidence_update(
                    analysis_result, message, positions, correlation_id
                )
                return execution_result
            else:
                # Low confidence - queue for manual review (AC: 5)
                review_result = await self._queue_for_manual_review(
                    analysis_result, message, correlation_id
                )
                return ExecutionResult.QUEUED_FOR_REVIEW, review_result

        except Exception as e:
            self.logger.error(
                f"Error processing context analysis: {e}",
                extra_fields={
                    "context_processing": {
                        "error": str(e),
                        "correlation_id": correlation_id,
                        "action": analysis_result.action,
                        "confidence": analysis_result.confidence
                    }
                }
            )
            return ExecutionResult.FAILED, {"error": str(e)}

    def _validate_analysis_result(
        self,
        analysis_result: ContextAnalysisResult,
        positions: list[Position]
    ) -> dict[str, Any]:
        """
        Validate analysis result for execution readiness.
        
        Args:
            analysis_result: Result to validate
            positions: Available positions
            
        Returns:
            Validation result with is_valid flag and errors
        """
        errors = []

        # Validate action
        valid_actions = ["breakeven", "close", "modify"]
        if analysis_result.action not in valid_actions:
            if analysis_result.action == "unknown":
                errors.append("Action determined as unknown - insufficient context")
            else:
                errors.append(f"Invalid action: {analysis_result.action}")

        # Validate target position exists
        if analysis_result.target_position:
            target_found = False
            for pos in positions:
                if str(pos.mt5_ticket) == str(analysis_result.target_position):
                    target_found = True
                    break

            if not target_found:
                errors.append(f"Target position {analysis_result.target_position} not found in open positions")
        else:
            if analysis_result.action in ["breakeven", "close", "modify"]:
                errors.append("Target position required for action but not specified")

        # Validate parameters based on action
        if analysis_result.action == "close":
            percentage = analysis_result.parameters.get("percentage")
            if percentage is not None:
                if not isinstance(percentage, (int, float)) or percentage <= 0 or percentage > 1:
                    errors.append(f"Invalid close percentage: {percentage}")

        elif analysis_result.action == "modify":
            new_sl = analysis_result.parameters.get("new_sl")
            new_tp = analysis_result.parameters.get("new_tp")
            if new_sl is None and new_tp is None:
                errors.append("Modify action requires new_sl or new_tp parameter")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors
        }

    async def _execute_high_confidence_update(
        self,
        analysis_result: ContextAnalysisResult,
        message: TelegramMessage,
        positions: list[Position],
        correlation_id: str
    ) -> tuple[ExecutionResult, dict[str, Any]]:
        """
        Execute high-confidence update by routing to appropriate processor.
        
        Args:
            analysis_result: High-confidence analysis result
            message: Original message
            positions: Open positions
            correlation_id: Correlation ID for tracking
            
        Returns:
            Tuple of execution result and details
        """
        # Find target position
        target_position = None
        for pos in positions:
            if str(pos.mt5_ticket) == str(analysis_result.target_position):
                target_position = pos
                break

        if not target_position:
            return ExecutionResult.FAILED, {"error": "Target position not found"}

        # Route to appropriate processor based on action
        execution_details = {
            "action": analysis_result.action,
            "target_position": analysis_result.target_position,
            "parameters": analysis_result.parameters,
            "confidence": analysis_result.confidence,
            "correlation_id": correlation_id,
            "execution_time": datetime.now().isoformat()
        }

        try:
            if analysis_result.action == "breakeven":
                result = await self._route_to_break_even_processor(
                    target_position, analysis_result, message, correlation_id
                )
            elif analysis_result.action == "close":
                result = await self._route_to_close_processor(
                    target_position, analysis_result, message, correlation_id
                )
            elif analysis_result.action == "modify":
                result = await self._route_to_modify_processor(
                    target_position, analysis_result, message, correlation_id
                )
            else:
                return ExecutionResult.INVALID_ACTION, {"error": f"Unsupported action: {analysis_result.action}"}

            # Log successful execution
            if result["success"]:
                await self._create_audit_trail(
                    target_position, analysis_result, message, True, None
                )
                execution_details.update(result)

                self.logger.info(
                    "High-confidence context update executed successfully",
                    extra_fields={
                        "context_processing": execution_details
                    }
                )

                return ExecutionResult.EXECUTED, execution_details
            else:
                # Execution failed
                await self._create_audit_trail(
                    target_position, analysis_result, message, False, result.get("error")
                )
                execution_details["error"] = result.get("error")

                self.logger.error(
                    "High-confidence context update execution failed",
                    extra_fields={
                        "context_processing": execution_details
                    }
                )

                return ExecutionResult.FAILED, execution_details

        except Exception as e:
            await self._create_audit_trail(
                target_position, analysis_result, message, False, str(e)
            )
            execution_details["error"] = str(e)

            self.logger.error(
                f"Exception during high-confidence update execution: {e}",
                extra_fields={
                    "context_processing": execution_details
                }
            )

            return ExecutionResult.FAILED, execution_details

    async def _queue_for_manual_review(
        self,
        analysis_result: ContextAnalysisResult,
        message: TelegramMessage,
        correlation_id: str
    ) -> dict[str, Any]:
        """
        Queue low-confidence update for manual review without execution.
        
        Args:
            analysis_result: Low-confidence analysis result
            message: Original message
            correlation_id: Correlation ID for tracking
            
        Returns:
            Review queue details
        """
        review_details = {
            "action": analysis_result.action,
            "target_position": analysis_result.target_position,
            "parameters": analysis_result.parameters,
            "confidence": analysis_result.confidence,
            "reasoning": analysis_result.reasoning,
            "correlation_id": correlation_id,
            "message_text": message.raw_text,
            "queued_at": datetime.now().isoformat(),
            "review_required": True
        }

        # Log for manual review (AC: 5)
        self.logger.warning(
            "Context update queued for manual review - LOW CONFIDENCE",
            extra_fields={
                "context_processing": review_details,
                "manual_review_required": True
            }
        )

        # Create audit trail for manual review
        if analysis_result.target_position:
            # Find position for audit trail
            async with self.repository_factory.get_session() as session:
                position_repo = self.repository_factory.get_position_repository()
                positions = await position_repo.list(session)
                target_position = None
                for pos in positions:
                    if str(pos.mt5_ticket) == str(analysis_result.target_position):
                        target_position = pos
                        break

                if target_position:
                    await self._create_audit_trail(
                        target_position, analysis_result, message, False,
                        f"Low confidence ({analysis_result.confidence}) - queued for manual review"
                    )

        return review_details

    async def _route_to_break_even_processor(
        self,
        position: Position,
        analysis_result: ContextAnalysisResult,
        message: TelegramMessage,
        correlation_id: str
    ) -> dict[str, Any]:
        """Route break even request to break_even.py processor."""
        # Import here to avoid circular imports
        from src.risk_manager.break_even import BreakEvenProcessor

        break_even_processor = BreakEvenProcessor(self.repository_factory)

        # Create break even request - move SL to entry price
        result = await break_even_processor.process_break_even_request(
            position=position,
            telegram_message_id=message.telegram_message_id,
            correlation_id=correlation_id
        )

        return {
            "success": result.get("success", False),
            "processor": "break_even",
            "new_sl": position.open_price,
            "error": result.get("error")
        }

    async def _route_to_close_processor(
        self,
        position: Position,
        analysis_result: ContextAnalysisResult,
        message: TelegramMessage,
        correlation_id: str
    ) -> dict[str, Any]:
        """Route close request to close_processor.py."""
        # Import here to avoid circular imports
        from src.risk_manager.close_processor import CloseProcessor

        close_processor = CloseProcessor(self.repository_factory)

        # Determine close parameters
        percentage = analysis_result.parameters.get("percentage", 1.0)  # Default to full close

        result = await close_processor.process_close_signal(
            position=position,
            close_percentage=percentage,
            telegram_message_id=message.telegram_message_id,
            correlation_id=correlation_id
        )

        return {
            "success": result.get("success", False),
            "processor": "close",
            "close_percentage": percentage,
            "error": result.get("error")
        }

    async def _route_to_modify_processor(
        self,
        position: Position,
        analysis_result: ContextAnalysisResult,
        message: TelegramMessage,
        correlation_id: str
    ) -> dict[str, Any]:
        """Route modify request to position modifier."""
        # Import here to avoid circular imports
        from src.risk_manager.position_modifier import PositionModifier

        position_modifier = PositionModifier(self.repository_factory)

        # Extract modification parameters
        new_sl = analysis_result.parameters.get("new_sl")
        new_tp = analysis_result.parameters.get("new_tp")

        result = await position_modifier.modify_position(
            position=position,
            new_sl=new_sl,
            new_tp=new_tp,
            telegram_message_id=message.telegram_message_id,
            correlation_id=correlation_id
        )

        return {
            "success": result.get("success", False),
            "processor": "modify",
            "new_sl": new_sl,
            "new_tp": new_tp,
            "error": result.get("error")
        }

    async def _create_audit_trail(
        self,
        position: Position,
        analysis_result: ContextAnalysisResult,
        message: TelegramMessage,
        success: bool,
        error_message: str | None
    ) -> None:
        """
        Create audit trail in position_updates table with LLM confidence scores.
        
        Args:
            position: Target position
            analysis_result: LLM analysis result
            message: Original message
            success: Whether execution was successful
            error_message: Error message if failed
        """
        try:
            async with self.repository_factory.get_session() as session:
                # Create position update record for audit trail (AC: 5)
                update_record = PositionUpdate(
                    position_id=position.id,
                    update_type=UpdateType.LLM_ANALYSIS,
                    field_name="llm_context_analysis",
                    old_value=f"confidence: {analysis_result.confidence}",
                    new_value=f"action: {analysis_result.action}, params: {analysis_result.parameters}",
                    telegram_message_id=message.telegram_message_id,
                    success=success,
                    error_message=error_message or analysis_result.reasoning
                )

                session.add(update_record)
                await session.commit()

        except Exception as e:
            self.logger.error(f"Failed to create audit trail: {e}")

    async def _log_validation_failure(
        self,
        analysis_result: ContextAnalysisResult,
        message: TelegramMessage,
        errors: list[str]
    ) -> None:
        """Log validation failure for analysis result."""
        self.logger.error(
            "Context analysis validation failed",
            extra_fields={
                "context_processing": {
                    "action": analysis_result.action,
                    "confidence": analysis_result.confidence,
                    "target_position": analysis_result.target_position,
                    "validation_errors": errors,
                    "message_hash": self._hash_text(message.raw_text)
                }
            }
        )

    def _hash_text(self, text: str) -> str:
        """Hash text for logging without exposing content."""
        import hashlib
        return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
