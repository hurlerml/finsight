package app.finsight.fints.job;

import com.fasterxml.jackson.annotation.JsonIgnore;

import java.time.Instant;
import java.util.UUID;

public final class GatewayJob {
    private final UUID id = UUID.randomUUID();
    private final Instant createdAt = Instant.now();
    private volatile Instant updatedAt = createdAt;
    private volatile JobStatus status = JobStatus.QUEUED;
    private volatile String message = "Queued";
    private volatile Object result;
    private volatile JobError error;

    public UUID getId() {
        return id;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public JobStatus getStatus() {
        return status;
    }

    public String getMessage() {
        return message;
    }

    public Object getResult() {
        return result;
    }

    public JobError getError() {
        return error;
    }

    @JsonIgnore
    public boolean isTerminal() {
        return status == JobStatus.COMPLETED || status == JobStatus.FAILED;
    }

    public synchronized void update(JobStatus nextStatus, String nextMessage) {
        if (isTerminal()) {
            return;
        }
        status = nextStatus;
        message = nextMessage;
        updatedAt = Instant.now();
    }

    public synchronized void complete(Object value) {
        result = value;
        error = null;
        status = JobStatus.COMPLETED;
        message = "Completed";
        updatedAt = Instant.now();
    }

    public synchronized void fail(String code, String detail) {
        result = null;
        error = new JobError(code, detail);
        status = JobStatus.FAILED;
        message = detail;
        updatedAt = Instant.now();
    }

    public record JobError(String code, String detail) {
    }
}
