package app.finsight.fints.hbci;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class GatewayHbciCallbackTest {
    @Test
    void prefersDecoupledAppApprovalWhenNoMechanismIsConfigured() {
        String selected = GatewayHbciCallback.selectTanMechanism(
                "911:card reader|946:app approval (decoupled)|942:sms code",
                null
        );

        assertThat(selected).isEqualTo("946");
    }

    @Test
    void honorsConfiguredMechanism() {
        String selected = GatewayHbciCallback.selectTanMechanism(
                "911:card reader|946:app approval",
                "911"
        );

        assertThat(selected).isEqualTo("911");
    }

    @Test
    void rejectsMechanismThatBankDoesNotOffer() {
        assertThatThrownBy(() -> GatewayHbciCallback.selectTanMechanism("946:app approval", "999"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("not offered");
    }

    @Test
    void honorsConfiguredTanMediumIgnoringCase() {
        assertThat(GatewayHbciCallback.selectTanMedium("Phone|Tablet", "phone"))
                .isEqualTo("Phone");
    }
}
