from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('tenants', '0001_initial'),
        ('bookings', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='RoomType',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hotels_roomtype_set', to='tenants.tenant')),
                ('name', models.CharField(max_length=100)),
                ('description', models.TextField(blank=True)),
                ('capacity', models.PositiveSmallIntegerField(default=2)),
                ('base_price', models.DecimalField(decimal_places=2, max_digits=8)),
                ('image', models.ImageField(blank=True, null=True, upload_to='hotels/rooms/')),
                ('amenities', models.JSONField(blank=True, default=list)),
            ],
            options={'abstract': False},
        ),
        migrations.CreateModel(
            name='Room',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hotels_room_set', to='tenants.tenant')),
                ('room_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='rooms', to='hotels.roomtype')),
                ('room_number', models.CharField(max_length=20)),
                ('floor', models.PositiveSmallIntegerField(default=1)),
                ('status', models.CharField(choices=[('available', 'Available'), ('occupied', 'Occupied'), ('maintenance', 'Maintenance'), ('reserved', 'Reserved')], default='available', max_length=20)),
                ('notes', models.TextField(blank=True)),
            ],
            options={'ordering': ['floor', 'room_number']},
        ),
        migrations.CreateModel(
            name='SeasonalPrice',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('tenant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hotels_seasonalprice_set', to='tenants.tenant')),
                ('room_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seasonal_prices', to='hotels.roomtype')),
                ('name', models.CharField(max_length=100)),
                ('start_date', models.DateField()),
                ('end_date', models.DateField()),
                ('price', models.DecimalField(decimal_places=2, max_digits=8)),
            ],
            options={'abstract': False},
        ),
        migrations.CreateModel(
            name='RoomBooking',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('room', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='room_bookings', to='hotels.room')),
                ('booking', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='room_booking', to='bookings.booking')),
            ],
        ),
        migrations.AddIndex(
            model_name='roombooking',
            index=models.Index(fields=['room', 'booking'], name='hotels_room_room_id_idx'),
        ),
    ]
