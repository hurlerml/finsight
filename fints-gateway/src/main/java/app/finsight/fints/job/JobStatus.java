package app.finsight.fints.job;

import com.fasterxml.jackson.annotation.JsonValue;

public enum JobStatus {
    QUEUED,
    RUNNING,
    AWAITING_USER_ACTION,
    COMPLETED,
    FAILED;

    @JsonValue
    public String jsonValue() {
        return name().toLowerCase();
    }
}
