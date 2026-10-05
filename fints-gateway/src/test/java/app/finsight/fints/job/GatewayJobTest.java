package app.finsight.fints.job;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class GatewayJobTest {
    @Test
    void completedJobCannotBeMovedBackToRunning() {
        GatewayJob job = new GatewayJob();

        job.complete("result");
        job.update(JobStatus.RUNNING, "late update");

        assertThat(job.getStatus()).isEqualTo(JobStatus.COMPLETED);
        assertThat(job.getMessage()).isEqualTo("Completed");
        assertThat(job.getResult()).isEqualTo("result");
    }

    @Test
    void failedJobDoesNotExposePartialResult() {
        GatewayJob job = new GatewayJob();

        job.fail("fints_error", "Bank rejected request");

        assertThat(job.isTerminal()).isTrue();
        assertThat(job.getResult()).isNull();
        assertThat(job.getError().code()).isEqualTo("fints_error");
    }
}
