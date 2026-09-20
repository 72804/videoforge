import { client } from "./api";
import { IS_DEV } from "./config";
import { ClientError } from "./errors";
import { telegram } from "./telegram";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export async function settleQuote(quoteId: string): Promise<void> {
  if (IS_DEV) {
    await client.confirmPayment(quoteId);
    return;
  }
  const current = await client.paymentStatus(quoteId);
  if (current.status === "PAID") return;
  if (current.status === "EXPIRED") {
    throw new ClientError({ code: "QUOTE_EXPIRED", message: "Price expired. Recalculate before generating." });
  }
  const invoice = await client.createInvoice(quoteId);
  const webapp = telegram();
  if (webapp?.openInvoice) {
    await new Promise<void>((resolve, reject) => {
      webapp.openInvoice?.(invoice.invoice_url, (status) => {
        if (status === "cancelled") {
          reject(new ClientError({ code: "PAYMENT_REQUIRED", message: "Payment was cancelled." }));
          return;
        }
        if (status === "failed") {
          reject(new ClientError({ code: "PAYMENT_REQUIRED", message: "Payment failed. Try again." }));
          return;
        }
        resolve();
      });
    });
  }
  for (let i = 0; i < 25; i += 1) {
    const next = await client.paymentStatus(quoteId);
    if (next.status === "PAID") return;
    if (next.status === "EXPIRED") {
      throw new ClientError({ code: "QUOTE_EXPIRED", message: "Price expired. Recalculate before generating." });
    }
    await sleep(700);
  }
  throw new ClientError({
    code: "PAYMENT_REQUIRED",
    message: "Payment is still pending. Reopen this screen to recover status.",
  });
}
