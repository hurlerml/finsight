package app.finsight.fints.service;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class FintsReadServiceTest {
    @Test
    void acceptsHttpsBankEndpoint() {
        assertThatCode(() -> FintsReadService.validateEndpoint("https://fints.example.test/fints"))
                .doesNotThrowAnyException();
    }

    @Test
    void rejectsPlainHttpEndpoint() {
        assertThatThrownBy(() -> FintsReadService.validateEndpoint("http://fints.example.test"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("HTTPS");
    }

    @Test
    void rejectsCredentialsEmbeddedInEndpoint() {
        assertThatThrownBy(() -> FintsReadService.validateEndpoint(
                "https://user:secret@fints.example.test"
        )).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejectsNonStandardPort() {
        assertThatThrownBy(() -> FintsReadService.validateEndpoint(
                "https://fints.example.test:8443/fints"
        )).isInstanceOf(IllegalArgumentException.class);
    }
}
