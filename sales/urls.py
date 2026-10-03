from django.urls import path

from . import views

app_name = "sales"

urlpatterns = [
    # Deals
    path("deals/", views.DealListView.as_view(), name="deal_list"),
    path("deals/new/", views.DealCreateView.as_view(), name="deal_create"),
    path("deals/<int:pk>/", views.DealDetailView.as_view(), name="deal_detail"),
    path("deals/<int:pk>/edit/", views.DealUpdateView.as_view(), name="deal_update"),
    path("deals/<int:pk>/delete/", views.DealDeleteView.as_view(), name="deal_delete"),

    # Proposals
    path(
        "leads/<int:pk>/convert-to-deal/",
        views.LeadConvertToDealView.as_view(),
        name="lead_convert_to_deal",
    ),
    path("proposals/", views.ProposalListView.as_view(), name="proposal_list"),
    path("proposals/new/", views.ProposalCreateView.as_view(), name="proposal_create"),
    path("proposals/<int:pk>/", views.ProposalDetailView.as_view(), name="proposal_detail"),
    path("proposals/<int:pk>/edit/", views.ProposalUpdateView.as_view(), name="proposal_update"),
    path("proposals/<int:pk>/delete/", views.ProposalDeleteView.as_view(), name="proposal_delete"),
    path("proposals/<int:pk>/download/", views.ProposalPDFDownloadView.as_view(), name="proposal_pdf_download"),
    path("proposals/<int:pk>/accept/", views.ProposalAcceptView.as_view(), name="proposal_accept"),
    path(
        "proposals/<int:pk>/create-client/",
        views.ProposalCreateClientView.as_view(),
        name="proposal_create_client",
    ),
    path(
        "proposals/<int:pk>/convert-to-contract/",
        views.ProposalConvertToContractView.as_view(),
        name="proposal_convert_to_contract",
    ),

    # Contracts
    path("contracts/", views.ContractListView.as_view(), name="contract_list"),
    path("contracts/new/", views.ContractCreateView.as_view(), name="contract_create"),
    path("contracts/<int:pk>/", views.ContractDetailView.as_view(), name="contract_detail"),
    path("contracts/<int:pk>/edit/", views.ContractUpdateView.as_view(), name="contract_update"),
    path("contracts/<int:pk>/delete/", views.ContractDeleteView.as_view(), name="contract_delete"),
    path("contracts/<int:pk>/download/", views.ContractPDFDownloadView.as_view(), name="contract_download"),
    path(
        "contracts/<int:pk>/generate-invoice/",
        views.ContractGenerateInvoiceView.as_view(),
        name="contract_generate_invoice",
    ),
    path(
        "contracts/sign/<uuid:token>/",
        views.ContractPublicSignView.as_view(),
        name="contract_public_sign",
    ),

    # Invoices
    path("invoices/", views.InvoiceListView.as_view(), name="invoice_list"),
    path("invoices/new/", views.InvoiceCreateView.as_view(), name="invoice_create"),
    path("invoices/<int:pk>/", views.InvoiceDetailView.as_view(), name="invoice_detail"),
    path("invoices/<int:pk>/edit/", views.InvoiceUpdateView.as_view(), name="invoice_update"),
    path("invoices/<int:pk>/delete/", views.InvoiceDeleteView.as_view(), name="invoice_delete"),
    path("invoices/<int:pk>/download/", views.InvoicePDFDownloadView.as_view(), name="invoice_download"),

    # Payments
    path("payments/", views.PaymentListView.as_view(), name="payment_list"),
    path("payments/new/", views.PaymentCreateView.as_view(), name="payment_create"),
    path("payments/<int:pk>/", views.PaymentDetailView.as_view(), name="payment_detail"),
    path("payments/<int:pk>/edit/", views.PaymentUpdateView.as_view(), name="payment_update"),
    path("payments/<int:pk>/delete/", views.PaymentDeleteView.as_view(), name="payment_delete"),

    # Email actions
    path("proposals/<int:pk>/send-email/", views.ProposalSendEmailView.as_view(), name="proposal_send_email"),
    path("contracts/<int:pk>/send-email/", views.ContractSendEmailView.as_view(), name="contract_send_email"),
    path("invoices/<int:pk>/send-email/", views.InvoiceSendEmailView.as_view(), name="invoice_send_email"),
    path("payments/<int:pk>/send-email/", views.PaymentSendEmailView.as_view(), name="payment_send_email"),
]
