package app.finsight.fints.api.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;

import java.time.LocalDate;

public record FintsJobRequest(
        @NotNull FintsOperation operation,
        @NotNull @Valid FintsCredentials credentials,
        @Valid AccountSelector account,
        LocalDate since,
        LocalDate until
) {
}
