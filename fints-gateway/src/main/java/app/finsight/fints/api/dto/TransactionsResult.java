package app.finsight.fints.api.dto;

import java.util.List;

public record TransactionsResult(List<TransactionResponse> transactions, BalanceResponse balance) {
}
