import wandb
from src.data_loading.datasets import AllBidsDataset, Dataset3D, HDF5Dataset
from src.nets.voxelmorph_layers import apply_deformation_field
from src.losses.losses import *
from src.utils.general import *
from src.nets.Morph import Morph
from tqdm import tqdm
from monai.data import DataLoader
from src.utils.brain_visualization import detailed_plot_from3d, detailed_morph
from src.utils.movement import translate_and_rotate
import os
import shutil


def calculate_loss(img, skull, annotations, d_field, v_field, log=False):

    # Segmentation results
    one_hot_mask = torch.nn.functional.one_hot(annotations.to(torch.int64))[0].permute(0, -1, 1, 2, 3)
    hematoma = one_hot_mask[:, 1].unsqueeze(dim=0).float()
    left_ventricle = one_hot_mask[:, 2].unsqueeze(dim=0).float()
    right_ventricle = one_hot_mask[:, 3].unsqueeze(dim=0).float()

    # Morphed bois
    morphed_img = apply_deformation_field(img, d_field)
    # print("hematoma", hematoma.shape)
    # print(annotations.shape)

    morphed_hematoma = apply_deformation_field(hematoma, d_field)
    morphed_left_ventricle = apply_deformation_field(left_ventricle, d_field)
    morphed_right_ventricle = apply_deformation_field(right_ventricle, d_field)
    morphed_skull = apply_deformation_field(skull, d_field)

    # TODO: get brain without skull

    # ---- LOSSES -----

    # Regularization items
    loss_jacobian = jacobian_loss(v_field, voxel_size=(0.434, 0.434, 3.0), seg_mask=hematoma,
                                  stripped_brain=img)  # TODO: parse the affine for size
    loss_l1_gradient = spatial_gradient_l1(v_field)

    # General items
    loss_hematoma_decrease = volume_loss(hematoma, morphed_hematoma)
    loss_skull = skull_loss(skull, morphed_skull)
    loss_ssim = ssim_loss(morphed_img)
    loss_jeffrey = jeffreys_divergence_loss(morphed_img, bins=20)

    # Ventricle based item
    loss_ventricle_overlap = ventricle_overlap(morphed_left_ventricle, morphed_right_ventricle)
    loss_ventricle_wrong_side = ventricle_wrong_side(morphed_left_ventricle, morphed_right_ventricle)

    big_loss = (10.0 * loss_jacobian +
                1.0 * loss_l1_gradient +
                loss_hematoma_decrease +
                10.0 * loss_skull +
                2.0 * loss_ventricle_overlap +
                loss_jeffrey +
                3.0 * loss_ssim + 
                loss_ventricle_wrong_side

                )

    if log:
        out = {
            "Jacobian": loss_jacobian.item(),
            "L1 gradient": loss_l1_gradient.item(),
            "Hematoma decrease": loss_hematoma_decrease.item(),
            "Skull decrease": loss_skull.item(),
            "SSIM": loss_ssim.item(),
            "Jeffrey": loss_jeffrey.item(),
            "Ventricle overlap": loss_ventricle_overlap.item(),
            "Ventricle wrong side": loss_ventricle_wrong_side.item()
        }
        wandb.log(out)

    return big_loss


def train_morph(run_name, num_epochs, location, data_location, batch_size=1, num_workers=8, lr=3e-4,
                input_spatial_shape=(512, 512, 128), log=True):
    print(f"Started morphing things out: {run_name}")

    save_location = f"{location}/outputs/morph/{run_name}"
    device = "cuda"

    try:
        os.mkdir(path=save_location)
    except FileExistsError:
        shutil.rmtree(save_location, ignore_errors=True)
        os.mkdir(path=save_location)

    os.mkdir(path=f"{save_location}/visuals")
    os.mkdir(path=f"{save_location}/v_fields")
    os.mkdir(path=f"{save_location}/weights")

    dataset = HDF5Dataset(f"{location}/{data_location}", with_skulls=True, with_annotations=True)
    dataloader = DataLoader(dataset, batch_size=batch_size, num_workers=num_workers, shuffle=True)

    model = Morph(input_spatial_shape).to(device)

    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.9993)

    model.train()

    for epoch in tqdm(range(num_epochs)):

        for d in dataloader:
            names = d['name']
            optimizer.zero_grad()
            img = d['ct'].to(device)

            morphed_image_full, velocity_field, deformation_field = model(img)

            loss = calculate_loss(img, d['skull'].to(device), d['annotation'].to(device), deformation_field,
                                  velocity_field, log=log)

            loss.backward()
            optimizer.step()
            wandb.log({"training_loss": loss.item()})

        # if epoch % 20 == 0:
        detailed_morph(img, morphed_image_full, deformation_field, use_wandb=True, cmap_d="coolwarm")


        if epoch % 200 == 0:
            torch.save(model.state_dict(), f"{save_location}/weights/{epoch}.pt")

        scheduler.step()
