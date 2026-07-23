from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin

# Ensure user is logged in and has a company
class BaseAppView(LoginRequiredMixin, TemplateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['userProfile'] = self.request.user.profile
        return context

class DashboardView(BaseAppView):
    template_name = "frontend/dashboard.html"

class ItemsView(BaseAppView):
    template_name = "frontend/items.html"

class PartiesView(BaseAppView):
    template_name = "frontend/parties.html"

class GoodsInView(BaseAppView):
    template_name = "frontend/goods_in.html"

class GoodsOutView(BaseAppView):
    template_name = "frontend/goods_out.html"

class SpoilageView(BaseAppView):
    template_name = "frontend/spoilage.html"

class PaymentsView(BaseAppView):
    template_name = "frontend/payments.html"

class ReportsView(BaseAppView):
    template_name = "frontend/reports.html"

class ProfileView(BaseAppView):
    template_name = "frontend/profile.html"