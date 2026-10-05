package app.finsight.fints.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record FintsCredentials(
        @NotBlank @Pattern(regexp = "\\d{8}") String blz,
        @NotBlank @Size(max = 100) String user,
        @NotBlank @Size(max = 100) String pin,
        @NotBlank @Size(max = 500) String endpoint,
        @NotBlank @Size(max = 25) String productId,
        @Size(max = 100) String customerId,
        @Size(max = 100) String tanMedium,
        @Size(max = 10) String tanMechanism
) {
}
