from rest_framework import serializers, generics
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from tenants.permissions import IsTenantOwner
from .models import RentalItem


class RentalItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentalItem
        fields = ('id', 'name', 'rental_type', 'description', 'price_per_day',
                  'deposit', 'status', 'image', 'city', 'specs', 'is_featured')


class RentalItemListView(generics.ListAPIView):
    serializer_class = RentalItemSerializer
    permission_classes = [AllowAny]
    search_fields = ['name', 'city', 'description']
    filterset_fields = ['rental_type', 'status', 'city']

    def get_queryset(self):
        qs = RentalItem.objects.filter(tenant=self.request.tenant, status='available')
        rental_type = self.request.query_params.get('type')
        city = self.request.query_params.get('city')
        if rental_type:
            qs = qs.filter(rental_type=rental_type)
        if city:
            qs = qs.filter(city__icontains=city)
        return qs


class RentalItemDetailView(generics.RetrieveAPIView):
    serializer_class = RentalItemSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        return RentalItem.objects.filter(tenant=self.request.tenant)


@api_view(['GET'])
@permission_classes([AllowAny])
def check_availability(request, pk):
    start = request.query_params.get('start_date')
    end = request.query_params.get('end_date')
    if not start or not end:
        return Response({'detail': 'start_date and end_date required.'}, status=400)
    try:
        item = RentalItem.objects.get(pk=pk, tenant=request.tenant)
    except RentalItem.DoesNotExist:
        return Response({'detail': 'Not found.'}, status=404)
    available = item.is_available_for(start, end)
    return Response({'available': available, 'item': item.name})


class RentalItemManageView(generics.CreateAPIView):
    serializer_class = RentalItemSerializer
    permission_classes = [IsTenantOwner]

    def perform_create(self, serializer):
        serializer.save(tenant=self.request.tenant)


class RentalItemUpdateView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = RentalItemSerializer
    permission_classes = [IsTenantOwner]

    def get_queryset(self):
        return RentalItem.objects.filter(tenant=self.request.tenant)
