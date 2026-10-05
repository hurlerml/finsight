package app.finsight.fints.api;

import app.finsight.fints.api.dto.FintsJobRequest;
import app.finsight.fints.job.FintsJobService;
import app.finsight.fints.job.GatewayJob;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.net.URI;
import java.util.UUID;

@RestController
@RequestMapping("/v1/jobs")
public class FintsJobController {
    private final FintsJobService jobs;

    public FintsJobController(FintsJobService jobs) {
        this.jobs = jobs;
    }

    @PostMapping
    public ResponseEntity<GatewayJob> create(@Valid @RequestBody FintsJobRequest request) {
        GatewayJob job = jobs.submit(request);
        return ResponseEntity.accepted()
                .location(URI.create("/v1/jobs/" + job.getId()))
                .body(job);
    }

    @GetMapping("/{id}")
    public GatewayJob get(@PathVariable UUID id) {
        return jobs.get(id);
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable UUID id) {
        jobs.delete(id);
        return ResponseEntity.noContent().build();
    }
}
